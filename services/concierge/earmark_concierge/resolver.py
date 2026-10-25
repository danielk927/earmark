"""Turn a spoken description into registry objects.

Order: exact name/alias match -> Moss (when ready) -> fuzzy names (rapidfuzz)
-> lexical scorer over notes and description. Ambiguity is decided here, in
code: Moss scores are not a sort key, so we take every plausible hit and ask
when more than one remains. Lexical evidence can widen a single Moss answer
into a question (honest uncertainty), never narrow it.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from earmark_contracts import RegistryObject

from .grammar import normalize
from .moss_index import ObjectIndex
from .world import World

log = logging.getLogger(__name__)

MAX_CANDIDATES = 3
FUZZY_MIN = 80.0
FUZZY_MARGIN = 5.0
LEXICAL_MIN = 0.5
LEXICAL_RATIO = 0.75
MOSS_TIMEOUT_S = 0.8  # a slow Moss answer must not hold up the turn
_STOP = {
    "i", "me", "my", "the", "a", "an", "some", "something", "for", "to", "of", "and", "or", "with",
    "that", "this", "it", "is", "are", "need", "want", "where", "find", "please", "can", "you",
    "your", "get", "thing", "things", "stuff", "use", "used", "put", "on", "in", "at", "from",
    "one", "which", "what", "do", "does", "have", "has", "be", "was", "were", "go", "goes", "kind",
    "our", "his", "her", "their", "item", "usually", "kept", "s",
}
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}


def stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("es") and not tok.endswith("ses"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokens(text: str) -> list[str]:
    return [stem(t) for t in normalize(text).replace("'", " ").split() if t not in _STOP]


def strip_query(q: str) -> str:
    s = normalize(q)
    s = re.sub(r"^(?:(?:my|the|a|an|some|our)\s+)+", "", s)
    return s


@dataclass
class Resolution:
    kind: str  # one | ambiguous | none
    object_ids: list[str] = field(default_factory=list)
    engine: str = "none"  # exact | moss | fuzzy | lexical | ordinal | none
    moss_ms: float | None = None
    moss_status: str = "disabled"  # ok | error | disabled | skipped (exact name match)


class Resolver:
    def __init__(self, world: World, index: ObjectIndex | None,
                 moss_min_score: float = 0.35, moss_margin: float = 0.08) -> None:
        self.world = world
        self.index = index
        self.moss_min_score = moss_min_score
        self.moss_margin = moss_margin
        self.last_moss_ms: float | None = None

    @property
    def engine(self) -> str:
        return "moss" if self.index is not None and self.index.status == "ready" else "fallback"

    async def on_registry(self) -> None:
        if self.index is not None:
            await self.index.sync(list(self.world.objects.values()))

    # ------------------------------------------------------------ stages

    def _pool(self, candidates: list[str] | None) -> list[RegistryObject]:
        objs = self.world.objects
        if candidates is None:
            return list(objs.values())
        return [objs[c] for c in candidates if c in objs]

    @staticmethod
    def _terms(o: RegistryObject) -> list[str]:
        return [strip_query(t) for t in [o.name, *o.aliases] if strip_query(t)]

    def exact(self, q: str, pool: list[RegistryObject]) -> list[str]:
        sq = " ".join(stem(t) for t in q.split())
        equal, contained = [], []
        for o in pool:
            terms = [" ".join(stem(t) for t in term.split()) for term in self._terms(o)]
            if sq in terms:
                equal.append(o.object_id)
            elif any(re.search(rf"\b{re.escape(t)}\b", sq) for t in terms):
                contained.append(o.object_id)
        return equal or contained

    def fuzzy(self, q: str, pool: list[RegistryObject]) -> list[str]:
        words = q.split()
        scored: list[tuple[float, str]] = []
        for o in pool:
            best = 0.0
            for term in self._terms(o):
                n = len(term.split())
                grams = [" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))]
                best = max(best, fuzz.ratio(q, term), *(fuzz.ratio(g, term) for g in grams))
            if best >= FUZZY_MIN:
                scored.append((best, o.object_id))
        if not scored:
            return []
        top = max(s for s, _ in scored)
        return [oid for s, oid in sorted(scored, key=lambda x: -x[0]) if s >= top - FUZZY_MARGIN]

    def lexical(self, q: str, pool: list[RegistryObject]) -> list[str]:
        qt = set(tokens(q))
        if not qt:
            return []
        fields = {}
        for o in pool:
            fields[o.object_id] = [
                (2.0, set(tokens(" ".join([o.name, *o.aliases])))),
                (1.0, set(tokens(o.notes))),
                (0.5, set(tokens(o.description))),
            ]
        everything = [set().union(*(f for _, f in fl)) for fl in fields.values()]

        def hit(tok: str, bag: set[str]) -> bool:
            return tok in bag or (len(tok) >= 4 and any(b.startswith(tok) or tok.startswith(b)
                                                       for b in bag if len(b) >= 4))

        n = len(fields)
        scores: list[tuple[float, str]] = []
        for oid, fl in fields.items():
            score = 0.0
            for tok in qt:
                df = sum(1 for bag in everything if hit(tok, bag))
                if df == 0:
                    continue
                w = max((wt for wt, bag in fl if hit(tok, bag)), default=0.0)
                score += w * math.log(1 + n / df)
            if score > 0:
                scores.append((score, oid))
        if not scores:
            return []
        top = max(s for s, _ in scores)
        if top < LEXICAL_MIN:
            return []
        return [oid for s, oid in sorted(scores, key=lambda x: -x[0]) if s >= top * LEXICAL_RATIO]

    async def moss(self, q: str, pool: list[RegistryObject], res: Resolution) -> list[str] | None:
        """Plausible Moss hits, or None when Moss is unavailable."""
        if self.index is None:
            res.moss_status = "disabled"
            return None
        t0 = time.perf_counter()
        try:
            hits = await asyncio.wait_for(self.index.query(q, top_k=5), MOSS_TIMEOUT_S)
        except Exception as e:
            res.moss_status = "error"
            log.info("moss query failed (%r); using fallback", e)
            return None
        res.moss_ms = (time.perf_counter() - t0) * 1000
        self.last_moss_ms = res.moss_ms
        res.moss_status = "ok"
        ids = {o.object_id for o in pool}
        hits = [h for h in hits if h.object_id in ids]
        if not hits:
            return []
        best = max(h.score for h in hits)
        ok = [h for h in hits if h.score >= self.moss_min_score and h.score >= best - self.moss_margin]
        return [h.object_id for h in sorted(ok, key=lambda h: -h.score)]

    # ------------------------------------------------------------ entry point

    async def resolve(self, query: str, candidates: list[str] | None = None,
                      strict: bool = False) -> Resolution:
        """strict: names only (exact, ordinal, fuzzy), for answers to "Do you mean A or B?"."""
        res = Resolution(kind="none")
        pool = self._pool(candidates)
        q = strip_query(query)
        if not q or not pool:
            return res

        if candidates is not None:
            words = q.split()
            for w in words:
                if w in _ORDINALS and _ORDINALS[w] < len(pool):
                    return self._done(res, [pool[_ORDINALS[w]].object_id], "ordinal")
            if "last" in words:
                return self._done(res, [pool[-1].object_id], "ordinal")

        exact = self.exact(q, pool)
        if strict:
            ids = exact or self.fuzzy(q, pool)
            return self._done(res, ids, "exact" if exact else "fuzzy") if ids else res
        if exact:
            if self.index is not None:
                res.moss_status = "skipped"
            return self._done(res, exact, "exact")
        moss_ids = await self.moss(q, pool, res)
        if moss_ids:
            lex = self.lexical(q, pool)
            if len(moss_ids) == 1 and len(lex) > 1 and moss_ids[0] in lex:
                moss_ids = [moss_ids[0]] + [i for i in lex if i != moss_ids[0]]
            return self._done(res, moss_ids, "moss")
        fz = self.fuzzy(q, pool)
        if fz:
            return self._done(res, fz, "fuzzy")
        lex = self.lexical(q, pool)
        if lex:
            return self._done(res, lex, "lexical")
        return res

    @staticmethod
    def _done(res: Resolution, ids: list[str], engine: str) -> Resolution:
        ids = list(dict.fromkeys(ids))[:MAX_CANDIDATES]
        res.object_ids = ids
        res.engine = engine
        res.kind = "one" if len(ids) == 1 else "ambiguous"
        return res

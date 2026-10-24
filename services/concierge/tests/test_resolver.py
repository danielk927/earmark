"""Resolver: exact, Moss (faked), fallbacks, ambiguity. Thresholds tuned on the seed objects."""
import pytest

from conftest import OBJECTS
from earmark_concierge.moss_index import Hit, MossIndex, doc_text
from earmark_concierge.resolver import Resolver
from earmark_concierge.world import World


class FakeIndex:
    def __init__(self, hits=None, fail=False):
        self.hits = hits or {}
        self.fail = fail
        self.status = "error" if fail else "ready"
        self.synced = None

    async def sync(self, objects):
        self.synced = [o.object_id for o in objects]

    async def query(self, text, top_k=5):
        if self.fail:
            raise RuntimeError("moss unavailable: NETWORK")
        return self.hits.get(text, [])

    async def close(self):
        pass


def world():
    w = World()
    w.set_objects(OBJECTS)
    return w


@pytest.mark.parametrize("q,ids,engine", [
    ("sugar", ["sugar"], "exact"),
    ("the sugar jar", ["sugar"], "exact"),
    ("my keys", ["keys"], "exact"),
    ("key", ["keys"], "exact"),
    ("pills", ["bp_meds"], "exact"),
    ("evening pills", ["bp_meds"], "exact"),
    ("black pepper", ["pepper"], "exact"),
    ("salt and pepper", ["salt", "pepper"], "exact"),
    ("suger", ["sugar"], "fuzzy"),
    ("sault", ["salt"], "fuzzy"),
    ("something for my eggs", ["salt", "pepper"], "lexical"),
    ("something for my coffee", ["sugar"], "lexical"),
    ("something sweet", ["sugar"], "lexical"),
    ("the little jar", ["salt", "sugar"], "lexical"),
    ("bluetooth tracker", ["keys"], "lexical"),
])
async def test_fallback_resolution_on_seed(q, ids, engine):
    r = await Resolver(world(), None).resolve(q)
    assert (r.object_ids, r.engine) == (ids, engine)
    assert r.kind == ("one" if len(ids) == 1 else "ambiguous")
    assert r.moss_status == "disabled"


@pytest.mark.parametrize("q", ["passport", "something to open the door", "paper", "malt", ""])
async def test_unknown(q):
    r = await Resolver(world(), None).resolve(q)
    assert r.kind == "none"


async def test_moss_failure_falls_back():
    r = await Resolver(world(), FakeIndex(fail=True)).resolve("something for my eggs")
    assert r.moss_status == "error" and r.engine == "lexical" and r.object_ids == ["salt", "pepper"]


async def test_moss_hits_thresholded_in_our_code_not_by_rank():
    # Moss orders by hybrid relevance; the lower-ranked hit has the higher score.
    hits = {"seasoning for breakfast": [Hit("pepper", 0.58), Hit("salt", 0.61), Hit("sugar", 0.20)]}
    r = await Resolver(world(), FakeIndex(hits)).resolve("seasoning for breakfast")
    assert r.engine == "moss" and r.moss_status == "ok" and r.moss_ms is not None
    assert r.object_ids == ["salt", "pepper"] and r.kind == "ambiguous"


async def test_moss_single_answer():
    hits = {"sweet stuff for tea": [Hit("sugar", 0.7), Hit("salt", 0.3)]}
    r = await Resolver(world(), FakeIndex(hits)).resolve("sweet stuff for tea")
    assert (r.kind, r.object_ids) == ("one", ["sugar"])


async def test_lexical_widens_a_single_moss_answer_into_a_question():
    hits = {"something for my eggs": [Hit("salt", 0.66), Hit("pepper", 0.41)]}
    r = await Resolver(world(), FakeIndex(hits)).resolve("something for my eggs")
    assert (r.kind, r.object_ids) == ("ambiguous", ["salt", "pepper"])


async def test_exact_name_wins_over_moss():
    # sugar's description mentions the salt jar, so Moss may rank sugar for "salt".
    hits = {"salt": [Hit("sugar", 0.6), Hit("salt", 0.59)]}
    r = await Resolver(world(), FakeIndex(hits)).resolve("salt")
    assert r.object_ids == ["salt"] and r.engine == "exact" and r.moss_status == "ok"


async def test_candidates_and_strict_mode():
    res = Resolver(world(), None)
    r = await res.resolve("the second one", candidates=["salt", "pepper"], strict=True)
    assert r.object_ids == ["pepper"] and r.engine == "ordinal"
    r = await res.resolve("sugar", candidates=["salt", "pepper"], strict=True)
    assert r.kind == "none"  # sugar is not a candidate; lexical over descriptions must not pick salt


async def test_registry_sync_reaches_index():
    idx = FakeIndex()
    w = world()
    await Resolver(w, idx).on_registry()
    assert idx.synced == [o.object_id for o in OBJECTS]


def test_moss_doc_text_has_every_field():
    salt = OBJECTS[0]
    assert doc_text(salt) == ("salt. table salt, sea salt. For cooking and for eggs. "
                              "Small glass jar with a white lid, identical to the sugar jar")


async def test_real_moss_index_without_credentials_reports_error():
    idx = MossIndex("bad-project", "bad-key", "earmark-test")
    with pytest.raises(RuntimeError):
        await idx.query("sugar")
    assert idx.status == "error"

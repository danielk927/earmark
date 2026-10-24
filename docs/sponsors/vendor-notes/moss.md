# Moss - vendor notes for Earmark

Researched 2026-10-24.
Unless marked otherwise, every claim below comes from the linked official page.
Anything I could not confirm is marked UNVERIFIED.
The hack pack summary is in `docs/sponsors/sponsor-packs/moss.md`.

Tip for agents: https://docs.moss.dev/llms.txt indexes every doc page.
Append `.md` to any docs URL to get the raw Markdown (for example https://docs.moss.dev/docs/start/quickstart.md).

## 1. Package and install

- PyPI package: `moss` (import name `moss`).
  Latest is **1.21.0**, released 2026-10-23.
  It pins the native Rust core `inferedge-moss-core==0.35.0`.
  Sources: https://pypi.org/project/moss/ and https://pypi.org/project/inferedge-moss-core/
- Requires Python >=3.10.
  The PyPI classifiers list 3.10 to 3.14 (https://pypi.org/project/moss/).
  The docs say "Python 3.10 or higher" (https://docs.moss.dev/docs/reference/python/api).
- **Verified locally:** `moss==1.21.0` installs and imports on CPython 3.12.12, macOS arm64, using `uv`.
- Install: `pip install moss` or `uv add moss` (https://docs.moss.dev/docs/start/quickstart).
  Pin `moss>=1.21,<2`.
  The docs warn that versions below 1.9.0 will stop loading models once the legacy download path is retired (same page).
- Core wheels for 0.35.0: macOS **arm64 only** (`macosx_11_0_arm64`), Linux x86_64 and aarch64 (`manylinux_2_28`), and Windows amd64 (https://pypi.org/project/inferedge-moss-core/#files).
  There is no macOS x86_64 wheel, so **Intel Macs are not supported**.
  Azure Linux hosting needs glibc 2.28 or newer.
- Runtime deps: `httpx`, `anyio`, `h11`, `typing-extensions` (PyPI metadata).
- Repo: https://github.com/usemoss/moss (BSD-2-Clause).
  Python samples are in `examples/python/`, and a hackathon voice-agent starter is in `moss-workshop/starter/`.

## 2. Auth

- The env vars are `MOSS_PROJECT_ID` and `MOSS_PROJECT_KEY` (https://docs.moss.dev/docs/integrate/authentication).
- Constructor: `MossClient(project_id: str, project_key: str, *, cache_path: Optional[str] = None)` (https://docs.moss.dev/docs/reference/python/classes/MossClient).
  I checked the signature by introspecting 1.21.0.
- **The client does not read the env vars itself.**
  Pass them explicitly: `MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])`.
  (I grepped the 1.21.0 source: it reads only `MOSS_CLOUD_API_BASE_URL`, `MOSS_INFERENCE_URL` and `MOSS_SESSION_CACHE_PATH` from the environment.)
- Get credentials at https://portal.usemoss.dev.
  Copy the Project ID, then create a key on the **API Keys** page.
  The key is shown once.
  Deleting a key revokes its tokens within about 20 s (https://docs.moss.dev/docs/integrate/authentication).
- The project key is exchanged for a short-lived access token at first use and refreshed before it expires (https://docs.moss.dev/docs/reference/telemetry, "Other data that leaves the device").
- `client.session(...)` validates credentials and raises if they are invalid (https://docs.moss.dev/docs/integrate/authentication).
- Hackathon credits: redeem code `CALHACKS` at https://portal.usemoss.dev/dashboard/settings/billing (hack pack).
- Optional CLI: `pip install moss-cli` (the binary is also named `moss`).
  It offers `moss init`, `moss index list`, `moss query <index> "<text>"` and `moss keys create` (https://docs.moss.dev/docs/integrations/moss-cli).

## 3. Two index models, and which one Earmark should use

The **session index** (`SessionIndex`) lives in process.
`add_docs`, `delete_docs`, `get_docs` and `query` all run in memory with no cloud round trip (about 1-10 ms).
Embedding also runs locally.
You can optionally call `push_index()` to the cloud or `save_to_disk()` (https://docs.moss.dev/docs/reference/python/classes/SessionIndex, https://docs.moss.dev/docs/integrate/sessions).

The **cloud (persistent) index** is created with `create_index`.
Changes go through `add_docs`/`delete_docs`, which run as async server-side build jobs.
Running processes then pull the new version with `load_index` (https://docs.moss.dev/docs/build/data-hydration-sync).

**Recommendation for Earmark: use a `SessionIndex` inside the concierge process, rebuilt from the local registry cache.**
Reasons:

- Only one process (the concierge) queries the registry.
  The registry is tiny (tens of docs) and changes at runtime, through dashboard label edits.
  That is the session use case in the hack pack and in https://docs.moss.dev/docs/build/real-time-local-indexing.
- A registry change becomes a local upsert or delete, measured in milliseconds.
  The cloud path would be an upload, a build job and a reload, which needs the network and takes seconds.
- With no `push_index()`, document text (object names and notes, possibly medication names) never leaves the Mac.
  Creating or adding docs to a cloud index uploads ids, text and metadata (https://docs.moss.dev/docs/reference/telemetry).
  This is a good point for the Microsoft "responsible design" criterion.
- Do not use `auto_refresh` on a cloud index.
  Each poll counts as billed session time, even when idle (https://docs.moss.dev/docs/integrate/storage-persistence).

## 4. API (Python, moss 1.21.0)

Every method below is `async` (I checked with `inspect.iscoroutinefunction` on 1.21.0).
The only sync call is the `MossClient(...)` constructor.

### Document shape

`DocumentInfo(id: str, text: str, metadata: Optional[Dict[str, str]] = None, embedding=None, payload: Optional[str] = None)` (https://docs.moss.dev/docs/reference/python/interfaces/DocumentInfo)

- Metadata values are **strings**.
  In dict or JSON input, booleans become `"true"`/`"false"` and numbers become decimal strings (https://docs.moss.dev/docs/reference/python/classes/MossClient, `create_index`).
- `payload` is an opaque string (for example JSON) that is stored and returned verbatim, never embedded or searched (DocumentInfo page).
  Use it to carry the object's id, name and tag back with each hit.
- An upsert replaces documents with matching `id`s, so keep ids stable (https://docs.moss.dev/docs/start/core-concepts).
- A chunk can hold at most 2,000 characters (about 512 tokens, the embedding model's input limit) (https://docs.moss.dev/docs/reference/errors).
  Earmark's object docs are far below that.

### MossClient (https://docs.moss.dev/docs/reference/python/classes/MossClient)

| Call | Returns | Notes |
| - | - | - |
| `await client.create_index(name, docs, model_id=None, *, wait=True)` | `MutationResult(job_id, index_name, doc_count)` | Cloud build; raises "Index already exists" if the name is taken (https://docs.moss.dev/docs/reference/errors). `model_id` defaults to `"moss-minilm"`. |
| `await client.add_docs(name, docs, MutationOptions(upsert=True))` | `MutationResult` | Cloud upsert, runs as a server-side job. |
| `await client.delete_docs(name, doc_ids)` | `MutationResult` | Cloud delete. |
| `await client.get_docs(name, GetDocumentsOptions(doc_ids=[...]))` | `List[DocumentInfo]` | |
| `await client.load_index(name, auto_refresh=False, polling_interval_in_seconds=600, cache_path=None)` | `str` | Required before `query`. Since 1.21.0, calling it on an already loaded index checks the cloud version and swaps in a newer one without interrupting queries (https://docs.moss.dev/docs/changelog). |
| `await client.query(name, text, QueryOptions(...))` | `SearchResult` | Runs in memory, about 1-10 ms. |
| `await client.unload_index(name)`, `await client.delete_index(name)`, `await client.list_indexes()`, `await client.get_index(name)` | | |
| `await client.get_job_status(job_id)` | `JobStatusResponse` | Status moves through `pending_upload`, `uploading`, `building`, `completed` (https://docs.moss.dev/docs/build/data-hydration-sync). |
| `await client.was_served_stale(name)` | `bool` | True when the index was served from the disk cache because the cloud was unreachable. The docs do not show it as async, but in 1.21.0 it is a coroutine. |
| `await client.session(index_name, model_id=None, *, auto_load_on_init=True)` | `SessionIndex` | Creates a session, or resumes the cloud index of the same name. `auto_load_on_init=False` starts empty. 1.21.0 also has undocumented `artifact_version` and `manifest_sha256` kwargs. |
| `await client.close()` | | Sends a final usage report and waits up to 2 s, then frees memory. Also works as `async with MossClient(...) as client:` (https://docs.moss.dev/docs/integrate/releasing-resources). |

### SessionIndex (https://docs.moss.dev/docs/reference/python/classes/SessionIndex)

| Call | Returns |
| - | - |
| `await session.add_docs(docs, MutationOptions(upsert=True))` | `(added_count, updated_count)` |
| `await session.delete_docs(doc_ids)` | `int` deleted |
| `await session.get_docs()` | `List[DocumentInfo]` |
| `await session.query(text, QueryOptions(...))` | `SearchResult` |
| `await session.push_index()` | `PushIndexResult` (creates or replaces the cloud index) |
| `await session.save_to_disk(cache_path=None)` / `await session.load_from_disk(cache_path=None)` | `None` / `int` docs loaded (1.16.0+) |
| `await session.close()` | |
| `session.doc_count`, `session.model_id`, `session.name` | properties |

It is UNVERIFIED whether `SessionIndex.add_docs` upserts by default.
The method is documented as "Add or update" and returns an updated count.
Passing `MutationOptions(upsert=True)` explicitly is harmless.

### QueryOptions (https://docs.moss.dev/docs/reference/python/interfaces/QueryOptions)

`QueryOptions(embedding=None, top_k=None, alpha=None, filter=None, group_by=None, min_score=None, candidate_depth=None)` (signature checked on 1.21.0).

- `alpha` sets the hybrid blend: `1.0` is pure semantic, `0.0` is pure keyword (BM25), and the default is `0.8` (https://docs.moss.dev/docs/integrate/hybrid-search).
- `filter` takes metadata operators `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin` and `$near`, composed with `$and`/`$or`.
- `min_score` drops hits below a 0-1 floor.
  **`SessionIndex.query` ignores `min_score` and `candidate_depth`**, so with a session, threshold in our own code (QueryOptions page).
- The docs default for `top_k` is not stated.
  Always pass it.

### Response shape

`SearchResult(docs: List[QueryResultDocumentInfo], query: str, index_name: Optional[str], time_taken_ms: Optional[int])` (https://docs.moss.dev/docs/reference/python/interfaces/SearchResult)

`QueryResultDocumentInfo(id, text, metadata, score, index_name, payload)` (https://docs.moss.dev/docs/reference/python/interfaces/QueryResultDocumentInfo).

**Score semantics** (https://docs.moss.dev/docs/integrate/retrieval#score-semantics):

- `score` runs from 0 to 1 and comes from vector similarity only.
- Results are ordered by hybrid relevance, so **score is not the sort key**, and a lower-ranked hit can have a higher score.
- With `alpha=0` every score is 0.
- Score is a per-model rescaled similarity, not a probability.
  Tune any threshold on our own seeded queries.

### Rebuilding when the registry changes

- **Session (recommended):** diff the registry against `session.get_docs()`.
  Then `delete_docs(removed_ids)` and `add_docs(all_or_changed_docs, MutationOptions(upsert=True))`.
  All of it is local.
  For a full reset, `close()` the session and open a new one with `auto_load_on_init=False`.
- **Cloud index:** `add_docs(..., MutationOptions(upsert=True))` / `delete_docs(...)` submit a server-side build job and return a `MutationResult` with a `job_id`.
  Poll `get_job_status(job_id)` until it reads `completed`.
  UNVERIFIED: whether these calls already block until the build finishes, the way `create_index` does with its default `wait=True`.
  Then call `load_index(name)` again to pull the new version (https://docs.moss.dev/docs/build/data-hydration-sync, "Force an immediate refresh").

## 5. Latency, models, limits, gotchas, offline

### Latency

- Queries run in memory in about 1-10 ms, depending on hardware (MossClient `query` docs, https://docs.moss.dev/docs/start/core-concepts).
- Measured by Moss on Linux arm64 with Python 3.12, moss 1.19.0 and `moss-minilm`: a text query took about 6 ms at the median and 9-10 ms at p95, embedding included (https://docs.moss.dev/docs/integrate/memory-sizing).
- Log `SearchResult.time_taken_ms`, which is an int in ms and may be `None`.
  Also log our own wall-clock `time.perf_counter()` around the `await` (sub-ms resolution) for the debug panel.
  Moss recommends tracking p50 and p95 (https://docs.moss.dev/docs/integrate/deployment-production).
- Cold start is the expensive part.
  The first index load in a process loads the embedding model (149 MiB, with a 370-380 MiB process peak while it loads) (https://docs.moss.dev/docs/integrate/memory-sizing).
  If the model is not cached, it is downloaded from `models.moss.link` (https://docs.moss.dev/docs/reference/telemetry).
  Open the session and run one warm-up query at concierge startup, never on the first user request.
  UNVERIFIED: whether the first query after loading is measurably slower than later ones.
- Session `add_docs` embeds locally in batches.
  On an Apple M2, 5,000 short captions took about 20 s, so rebuilding a registry of tens of objects should take well under a second (https://docs.moss.dev/docs/changelog, `inferedge-moss-core` 0.27.0 entry).
- `close()` can block for up to 2 s, so keep it off the hot path (https://docs.moss.dev/docs/integrate/releasing-resources).

### Embedding models (https://docs.moss.dev/docs/start/core-concepts)

- `moss-minilm` is the default: fast and light, good for edge and offline use.
- `moss-mediumlm` is more accurate at reasonable speed.
- `moss-litelm` is the on-device default on iOS.
- `custom` means bring your own vectors, passed in `DocumentInfo.embedding` and `QueryOptions.embedding`.
- "HQ / HP embedding models" are Enterprise only (https://docs.moss.dev/docs/pricing).
- For "something for my eggs" style paraphrase, start with `moss-minilm` at `alpha=0.8`.
  If salt and pepper do not rank on top, try `moss-mediumlm`.
  Model choice is fixed per index or session.

### Plan limits (Developer, free) (https://docs.moss.dev/docs/pricing)

- 1 project, 3 indexes, 500 MB storage, 50 MB ingest a month, 60 session minutes a month.
- Local queries are unlimited and never metered.
- UNVERIFIED: exactly what accrues "session minutes".
  The docs say auto-refresh polls count, and the meter was renamed from "Voice minutes" (https://docs.moss.dev/docs/changelog).
  A concierge that keeps a session open all weekend might burn through 60 minutes.
  Redeem `CALHACKS` and watch the portal's Usage page after the first hour.

### Gotchas

- You must load an index (or open a session) before querying; "there is no cloud-query-without-loading path" (https://docs.moss.dev/docs/start/core-concepts).
- `create_index` on an existing name raises (https://docs.moss.dev/docs/reference/errors).
- Index names may not be blank, `.` or `..`, or contain `/` or control characters, and are at most 256 bytes (same page).
- Telemetry is always on.
  It sends index and session names, counts and per-query timings, but never query text or document text (https://docs.moss.dev/docs/reference/telemetry).
  Keep personal data out of index names: use `earmark-objects`, not a person's name.
- Errors raise `MossError` (a `RuntimeError`) with a stable `.code`: `INVALID_ARGUMENT`, `NOT_FOUND`, `UNAUTHORIZED`, `NETWORK`, `DESERIALIZATION`, `MODEL_UNAVAILABLE` or `INTERNAL`.
  Branch on `.code`, not the message (https://docs.moss.dev/docs/reference/python/interfaces/MossError).
  A closed client raises a plain `RuntimeError`.
- Each Python client and session keeps background threads until garbage collected (https://docs.moss.dev/docs/integrate/releasing-resources).
  Make one long-lived client per process.
- The API is async-only.
  If the concierge is not asyncio-based, run Moss on one dedicated event-loop thread and keep that loop for the client's whole lifetime.
  UNVERIFIED: whether using one client from several event loops is safe.

### Offline behavior

- **Queries never leave the device.**
  Query text is embedded locally, and there is no cloud query (https://docs.moss.dev/docs/reference/telemetry, "Queries never leave the device").
  Once the session (or loaded index) and its model are in memory, queries work without internet.
  Telemetry is held in memory and re-sent later (same page).
- **Startup needs the network.**
  The project key is exchanged for a token at first use.
  `session()` validates credentials.
  Loading a built-in embedding model, "cached or not", contacts the Moss service for a short-lived model key, and "Loading fails while the Moss service can't be reached" (https://docs.moss.dev/docs/reference/telemetry, https://docs.moss.dev/docs/integrate/authentication).
- With a cloud index and `cache_path` (1.14.0+), `load_index` serves the on-disk snapshot when the cloud is unreachable.
  But "a built-in embedding model may not open, so text queries with `alpha` above 0 can fail".
  Keyword-only queries (`alpha=0`) and queries with a caller-supplied embedding keep working (https://docs.moss.dev/docs/integrate/storage-persistence).
- UNVERIFIED: whether `client.session(..., auto_load_on_init=False)` followed by `session.load_from_disk()` works fully offline.
  The docs imply the model load still needs the service.
- UNVERIFIED: how long an already-warm process keeps serving queries offline, for example past token expiry.
  The docs say queries are local, but I could not test with real credentials.

## 6. Minimal snippet for Earmark (session index)

Adapted from https://docs.moss.dev/docs/reference/python/sessions and https://docs.moss.dev/docs/start/quickstart.
I checked every call signature and its async-ness against moss 1.21.0 on Python 3.12.
**I have not run it against the live service, because I had no credentials - UNVERIFIED end to end.**

```python
import asyncio
import json
import os
import time

from moss import DocumentInfo, MossClient, MossError, MutationOptions, QueryOptions

INDEX = "earmark-objects"  # sent in telemetry: no personal data in the name


def to_doc(obj: dict) -> DocumentInfo:
    parts = [obj["name"], ", ".join(obj.get("aliases", [])), obj.get("notes", ""), obj.get("description", "")]
    return DocumentInfo(
        id=obj["id"],
        text=". ".join(p for p in parts if p),
        metadata={"name": obj["name"]},  # values must be strings
        payload=json.dumps({"id": obj["id"], "name": obj["name"]}),
    )


async def main() -> None:
    client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
    # Local in-process index; skip pulling any cloud copy - the registry is the source of truth.
    session = await client.session(index_name=INDEX, auto_load_on_init=False)

    async def rebuild(objects: list[dict]) -> None:
        docs = [to_doc(o) for o in objects]
        stale = {d.id for d in await session.get_docs()} - {d.id for d in docs}
        if stale:
            await session.delete_docs(list(stale))
        await session.add_docs(docs, MutationOptions(upsert=True))

    await rebuild([
        {"id": "salt", "name": "salt", "aliases": ["sea salt"], "notes": "for seasoning eggs and soup"},
        {"id": "pepper", "name": "black pepper", "aliases": ["pepper"], "notes": "seasoning, grinder"},
        {"id": "sugar", "name": "sugar", "aliases": ["sweetener"], "notes": "for coffee and baking"},
    ])
    await session.query("warm up", QueryOptions(top_k=1))  # pay model/first-query cost at startup

    t0 = time.perf_counter()
    try:
        res = await session.query("something for my eggs", QueryOptions(top_k=3, alpha=0.8))
    except MossError as e:  # e.code: NETWORK, MODEL_UNAVAILABLE, NOT_FOUND, ...
        print("moss failed", e.code)  # fall back to the local alias/keyword grammar
        return
    wall_ms = (time.perf_counter() - t0) * 1000
    print(f"moss query wall={wall_ms:.2f}ms core={res.time_taken_ms}ms")
    for d in res.docs:  # hybrid order; score is vector-only and NOT the sort key
        print(d.id, round(d.score, 3), d.payload)

    await client.close()  # also closes the session; may block up to 2 s


asyncio.run(main())
```

The ambiguity rule for definition-of-done item 5 ("asks which one") lives in our code, not in Moss.
For example: take every hit whose score is at least T and within D of the best hit.
If more than one remains, ask the user.
Tune T and D on the seeded registry.

## 7. Where the Earmark brief conflicts with or leaves out official materials

1. **Offline rule (brief section 2, "must work with no internet except the speech API").**
   Moss query is local, but a cold start is not.
   Credential validation and loading the built-in embedding model both need the Moss service (section 5, Offline behavior).
   The concierge must start online and keep the process alive.
   On a `MossError` (`NETWORK`, `MODEL_UNAVAILABLE`, `UNAUTHORIZED`), or if Moss is not ready, the resolver must fall back to a local alias/keyword match.
   The demo-risk agent should test a concierge cold start with Wi-Fi off.
2. **"Rebuild it on every registry change" (5.D).**
   This is fine with a session, where it is a local upsert/delete.
   It is costly with a cloud index, where every change is a server build job plus a reload, needs the network, and with `auto_refresh` bills session minutes.
   The brief does not say which index type to use.
   The hack pack says persistent indexes should be loaded at startup, not recreated each time.
   Use a session (section 3).
3. **Definition of done item 5.**
   Moss returns ranked hits with scores, not a "these two are ambiguous" verdict.
   `min_score` is ignored on sessions, so thresholding and the clarifying question have to be our code (section 4, Score semantics).
4. **Sponsor resources table (2.5) expects judging criteria in the hack pack.**
   The pack has none.
   Devpost lists only "Best Use of Moss", 1 winner, "$996 in cash" / "Airpod Max/pros" (https://cal-hacks-13-0.devpost.com/).
   See `docs/sponsors/sponsor-packs/moss.md`.
5. **Moss Inference.**
   The hack pack gives a full section to Moss Inference, an OpenAI-compatible chat API with retrieval on the same host and <200 ms TTFT (https://docs.moss.dev/docs/reference/python/inference).
   The brief routes all LLM calls to Bitdeer.
   This is not a conflict, but judges of "Best Use of Moss" may weigh depth of use - UNVERIFIED.
   Do not switch without the human's approval, because Bitdeer tool calling is a separate sponsor deliverable.
6. **Platform.**
   The brief assumes a Mac demo machine.
   The Moss native core ships macOS arm64 wheels only, so the demo Mac must be Apple Silicon (https://pypi.org/project/inferedge-moss-core/#files).
7. **Python version.**
   The brief says Python 3.11+.
   Moss needs 3.10+, so 3.11 and 3.12 are both fine, and I verified 3.12.

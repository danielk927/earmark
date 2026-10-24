"""Registry store: cache/seed precedence, object_id derivation, label handling."""
from __future__ import annotations

import json
import shutil

from earmark_contracts import Label, Registry

from conftest import ROOT, UNKNOWN
from earmark_hub.registry import RegistryStore, derive_object_id, normalize_tag


def store(tmp_path, cache=None) -> RegistryStore:
    seed = tmp_path / "seed.json"
    shutil.copy(ROOT / "config" / "objects.seed.json", seed)
    cache_path = tmp_path / "cache.json"
    if cache is not None:
        cache_path.write_text(cache)
    return RegistryStore(cache_path, seed)


def test_derive_object_id():
    assert derive_object_id("Honey", set()) == "honey"
    assert derive_object_id("Peanut Butter!", set()) == "peanut_butter"
    assert derive_object_id("  Grandma's Tea  ", set()) == "grandma_s_tea"
    assert derive_object_id("honey", {"honey", "honey_2"}) == "honey_3"
    assert derive_object_id("!!!", set()) == "object"
    assert derive_object_id("Café", set()) == "caf"


def test_normalize_tag():
    assert normalize_tag("04:a1:b2") == "04A1B2"
    assert normalize_tag(" 04a1b2c3d4e502 ") == "04A1B2C3D4E502"
    assert normalize_tag("fob_keys") == "FOB_KEYS"


def test_loads_seed_without_cache(tmp_path):
    s = store(tmp_path)
    assert {o.object_id for o in s.objects} == {"salt", "sugar", "pepper", "bp_meds", "keys"}
    assert s.version is None


def test_cache_wins_over_seed(tmp_path):
    reg = json.loads((ROOT / "contracts" / "examples" / "registry" / "02.json").read_text())
    s = store(tmp_path, cache=json.dumps(reg))
    assert [o.object_id for o in s.objects] == ["salt", "sugar"] and s.version == 1761350400000


def test_invalid_cache_falls_back_to_seed(tmp_path):
    s = store(tmp_path, cache="{not json")
    assert len(s.objects) == 5


def test_label_creates_object_and_writes_cache(tmp_path):
    s = store(tmp_path)
    oid, created = s.apply_label(Label(tag=UNKNOWN.lower(), name="Honey", aliases=["the honey jar"], spot=1))
    assert (oid, created) == ("honey", True)
    honey = s.find_by_tag(UNKNOWN)
    assert honey.tag == UNKNOWN and honey.home_spot == 1 and honey.aliases == ["the honey jar"]
    assert honey.notes == "" and honey.is_medication is False and honey.fob_id is None
    cached = Registry.model_validate_json(s.cache_path.read_text())
    assert "honey" in {o.object_id for o in cached.objects}
    # A restart reads the cache, so the label survives.
    assert RegistryStore(s.cache_path, s.seed_path).find_by_tag(UNKNOWN).object_id == "honey"


def test_label_renames_object_with_that_tag(tmp_path):
    s = store(tmp_path)
    oid, created = s.apply_label(Label(tag="04A1B2C3D4E501", name="kosher salt", aliases=["salt"]))
    assert (oid, created) == ("salt", False)
    salt = s.find_by_tag("04A1B2C3D4E501")
    assert salt.name == "kosher salt" and salt.aliases == ["salt"] and salt.home_spot == 2
    assert len(s.objects) == 5


def test_label_deduplicates_object_ids(tmp_path):
    s = store(tmp_path)
    oid, created = s.apply_label(Label(tag="04FFFFFFFFFF01", name="Salt", aliases=[]))
    assert (oid, created) == ("salt_2", True)


def test_differs_by_version(tmp_path):
    s = store(tmp_path)
    reg = s.registry.model_copy(update={"version": 5.0})
    assert s.differs(reg)
    s.replace(reg)
    assert not s.differs(reg.model_copy(update={"objects": []}))  # same version: unchanged
    assert s.differs(reg.model_copy(update={"version": 6.0}))

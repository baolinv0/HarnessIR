import copy
import pytest
from hir_manual.cache import EvidenceCache
from hir_manual.tool_registry import load_profile, make_contract
from hir_manual.storage import write_json, read_json
from local_fixtures import synthetic_registry, face_evidence


def test_empty_success_can_cache_but_corruption_misses(tmp_path):
    entry = synthetic_registry(tmp_path)
    contract = make_contract("a"*64,"T2_FACE",load_profile(),entry)
    source = tmp_path/"result"
    face_evidence(source,contract)
    cache = EvidenceCache(tmp_path/"cache")
    with cache.lock("T2_FACE",__import__('hir_manual.cache',fromlist=['make_cache_key']).make_cache_key(contract)):
        path = cache.publish(contract,source)
    assert cache.lookup(contract) == path
    (path/"maps/faces.png").write_bytes(b"corrupt")
    assert cache.lookup(contract) is None


def test_failure_never_becomes_empty_cache(tmp_path):
    entry = synthetic_registry(tmp_path)
    contract = make_contract("a"*64,"T2_FACE",load_profile(),entry)
    source = tmp_path/"result"
    manifest = face_evidence(source,contract)
    manifest.update(status="error",error="model_missing")
    write_json(source/"evidence.json",manifest)
    with pytest.raises(ValueError):
        EvidenceCache(tmp_path/"cache").publish(contract,source)


def test_same_key_has_one_computing_owner(tmp_path):
    from filelock import Timeout
    cache = EvidenceCache(tmp_path/"cache")
    with cache.lock("T2_FACE","a"*64):
        with pytest.raises(Timeout):
            with cache.lock("T2_FACE","a"*64):
                pass
def test_full_frame_padding_is_valid_but_roi_must_remain_inside(tmp_path):
    import pytest
    from hir_manual.local_evidence import validate_local_evidence
    from hir_manual.tool_registry import make_contract,load_profile
    from hir_manual.storage import write_json
    from local_fixtures import synthetic_registry,face_evidence
    entry=synthetic_registry(tmp_path)
    contract=make_contract("a"*64,"T2_FACE",load_profile(),entry)
    data=face_evidence(tmp_path/"result",contract)
    data["views"].append({"id":"sdk_letterbox","grid_shape":[640,640],"view_to_canonical":[[1/640,0,0],[0,1/320,-.5],[0,0,1]],"kind":"full_frame"})
    write_json(tmp_path/"result/evidence.json",data)
    validate_local_evidence(tmp_path/"result",contract)
    data["views"][-1]["kind"]="roi"
    write_json(tmp_path/"result/evidence.json",data)
    with pytest.raises(ValueError):
        validate_local_evidence(tmp_path/"result",contract)


def test_canonicalizer_versions_are_distinct_cache_identities(tmp_path):
    from hir_manual.cache import make_cache_key
    entry = synthetic_registry(tmp_path)
    legacy = make_contract("a"*64, "T2_FACE", load_profile(), entry)
    stable = make_contract("a"*64, "T2_FACE", load_profile(), entry,
                           canonicalizer_version="hir_rgb8_exif_icc_v2_stablepng")
    assert legacy["canonicalizer_version"] == "hir_rgb8_exif_icc_v1"
    assert make_cache_key(legacy) != make_cache_key(stable)
    source = tmp_path / "legacy_result"
    face_evidence(source, legacy)
    cache = EvidenceCache(tmp_path / "cache")
    cache.publish(legacy, source)
    assert cache.lookup(legacy) is not None
    assert cache.lookup(stable) is None


def test_metadata_version_helper_never_upgrades_unversioned_cases():
    from hir_manual.tool_registry import canonicalizer_version_from_metadata
    assert canonicalizer_version_from_metadata({}) == "hir_rgb8_exif_icc_v1"
    assert canonicalizer_version_from_metadata({"canonicalizer_version": "hir_rgb8_exif_icc_v1"}) == "hir_rgb8_exif_icc_v1"
    assert canonicalizer_version_from_metadata({"canonicalizer_version": "hir_rgb8_exif_icc_v2_stablepng"}) == "hir_rgb8_exif_icc_v2_stablepng"
    with pytest.raises(ValueError):
        canonicalizer_version_from_metadata({"canonicalizer_version": None})

"""Transport fixtures; do not claim real GPU inference."""
import zipfile
from hir_manual.bundles import export_missing_jobs, import_cache_bundle
from hir_manual.storage import read_json, write_json
from hir_manual.tool_registry import load_profile
from local_fixtures import synthetic_registry, face_evidence


def bundle_fixture(tmp_path, photo):
    synthetic_registry(tmp_path)
    manifest = tmp_path / "photos.json"
    write_json(manifest, [{"sample_id": "fixture", "input_path": str(photo)}])
    export = export_missing_jobs(manifest, load_profile(), tmp_path/"jobs.zip", tmp_path, ["T2_FACE"])
    with zipfile.ZipFile(export) as z:
        z.extractall(tmp_path/"result")
    index = read_json(tmp_path/"result/bundle.json")
    entry = index["entries"][0]
    evidence = face_evidence(tmp_path/"result/evidence", entry["contract"])
    evidence["original_sha256"] = entry["original_sha256"]
    write_json(tmp_path/"result/evidence/evidence.json", evidence)
    entry["evidence_dir"] = "evidence"
    index["bundle_kind"] = "cache_results"
    write_json(tmp_path/"result/bundle.json", index)
    return index


def pack(tmp_path):
    output = tmp_path / "results.zip"
    with zipfile.ZipFile(output, "w") as z:
        for p in (tmp_path/"result").rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(tmp_path/"result").as_posix())
    return output


def test_import_exact_contract_then_cache_hit(tmp_path,photo):
    index = bundle_fixture(tmp_path,photo)
    assert index["entries"][0]["contract"]["canonicalizer_version"] == "hir_rgb8_exif_icc_v2_stablepng"
    bundle = pack(tmp_path)
    result = import_cache_bundle(bundle,tmp_path/"Data/annotations/cache")
    assert result.imported == 1 and result.rejected == 0
    assert import_cache_bundle(bundle,tmp_path/"Data/annotations/cache").existing == 1


def test_duplicate_entries_rejected_before_publish(tmp_path,photo):
    index = bundle_fixture(tmp_path,photo)
    index["entries"].append(index["entries"][0])
    write_json(tmp_path/"result/bundle.json",index)
    result = import_cache_bundle(pack(tmp_path),tmp_path/"Data/annotations/cache")
    assert result.rejected and result.imported == 0


def test_original_hash_and_contract_mismatch_rejected(tmp_path,photo):
    bundle_fixture(tmp_path,photo)
    path = tmp_path/"result/evidence/evidence.json"
    data = read_json(path)
    data["original_sha256"] = "9"*64
    write_json(path,data)
    result = import_cache_bundle(pack(tmp_path),tmp_path/"Data/annotations/cache")
    assert result.rejected and "original SHA" in result.messages[0]


def test_zip_path_traversal_rejected(tmp_path):
    with zipfile.ZipFile(tmp_path/"unsafe.zip","w") as z:
        z.writestr("../escape.json","{}")
    result = import_cache_bundle(tmp_path/"unsafe.zip",tmp_path/"Data/annotations/cache")
    assert result.rejected and not (tmp_path/"escape.json").exists()


def test_bundle_canonicalizer_version_cannot_be_relabelled(tmp_path, photo):
    index = bundle_fixture(tmp_path, photo)
    index["entries"][0]["contract"]["canonicalizer_version"] = "hir_rgb8_exif_icc_v1"
    write_json(tmp_path / "result/bundle.json", index)
    result = import_cache_bundle(pack(tmp_path), tmp_path / "Data/annotations/cache")
    assert result.rejected == 1 and result.imported == 0


def test_bundle_unversioned_source_preserves_legacy_contract(tmp_path, photo, monkeypatch):
    import hir_manual.cases as cases
    save = cases.write_json
    def legacy_metadata(path, value):
        if path.name == "metadata.json":
            value = {k: v for k, v in value.items() if k != "canonicalizer_version"}
        return save(path, value)
    monkeypatch.setattr(cases, "write_json", legacy_metadata)
    index = bundle_fixture(tmp_path, photo)
    assert index["entries"][0]["contract"]["canonicalizer_version"] == "hir_rgb8_exif_icc_v1"
    result = import_cache_bundle(pack(tmp_path), tmp_path / "Data/annotations/cache")
    assert result.imported == 1 and result.rejected == 0

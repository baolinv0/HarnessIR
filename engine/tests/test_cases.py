import io
import struct

import pytest
from PIL import Image, ImageCms, ImageOps
from hir_manual.cases import create_case
from hir_manual.storage import CasePaths, sha256_file, read_json


def test_original_unchanged_and_snapshot(tmp_path, photo):
    before = photo.read_bytes()
    state = create_case(tmp_path, photo, "Restore conservatively", {})
    case = CasePaths(state.case_id, tmp_path)
    assert case.path("input/original.png").read_bytes() == before == photo.read_bytes()
    assert state.input_sha256 == sha256_file(case.path("input/canonical.png"))
    assert state.config_sha256 == sha256_file(case.path("case_config.json"))
    assert read_json(case.path("input/metadata.json"))["operations"] == []


def test_exif_rotation(tmp_path):
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (20, 10)).save(source, exif=exif)
    state = create_case(tmp_path, source, "Restore", {})
    with Image.open(CasePaths(state.case_id, tmp_path).path("input/canonical.png")) as im:
        assert im.size == (10, 20)


def test_oversize_explicit_error(tmp_path, photo):
    with pytest.raises(ValueError):
        create_case(tmp_path, photo, "Restore", {"max_input_pixels": 10})


def test_icc_canonical_stable_across_profile_creation_dates(tmp_path, monkeypatch):
    # Legal sRGB profiles differ only in ICC header creation time. The profile
    # affects colour conversion, but its timestamp must not affect PNG identity.
    profile_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    targets = []
    for date in ((2025, 1, 2, 3, 4, 5), (2026, 10, 13, 6, 7, 8)):
        timed = bytearray(profile_bytes)
        timed[24:36] = struct.pack(">6H", *date)
        targets.append(ImageCms.ImageCmsProfile(io.BytesIO(timed)))
    assert targets[0].tobytes() != targets[1].tobytes()
    image = Image.new("RGB", (3, 2))
    image.putdata([(10, 20, 30), (100, 150, 200), (255, 1, 5),
                   (20, 250, 15), (220, 190, 150), (0, 0, 0)])
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / "icc_rotated.png"
    image.save(source, icc_profile=profile_bytes, exif=exif)
    original_bytes = source.read_bytes()
    with Image.open(source) as original:
        expected = ImageCms.profileToProfile(ImageOps.exif_transpose(original),
                                            ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes)),
                                            targets[0], outputMode="RGB")
    created_profiles = iter(targets)
    monkeypatch.setattr("hir_manual.cases.ImageCms.createProfile", lambda _: next(created_profiles))
    cases = [CasePaths(create_case(tmp_path, source, "Restore", {}).case_id, tmp_path)
             for _ in range(2)]
    assert cases[0].path("input/canonical.png").read_bytes() == cases[1].path("input/canonical.png").read_bytes()
    for case in cases:
        metadata = read_json(case.path("input/metadata.json"))
        assert metadata["canonicalizer_version"] == "hir_rgb8_exif_icc_v2_stablepng"
        assert metadata["operations"] == ["EXIF_orientation", "ICC_to_sRGB"]
        assert case.path("input/original.png").read_bytes() == original_bytes == source.read_bytes()
        with Image.open(case.path("input/canonical.png")) as canonical:
            assert canonical.size == expected.size == (2, 3)
            assert canonical.mode == "RGB"
            assert canonical.tobytes() == expected.tobytes()
            assert canonical.info == {}


def test_lab_icc_conversion_preserves_converted_pixels_and_original(tmp_path):
    source = tmp_path / "lab.tiff"
    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB"))
    srgb = ImageCms.createProfile("sRGB")
    image = Image.new("LAB", (2, 1))
    image.putdata([(150, 180, 90), (80, 110, 160)])
    expected = ImageCms.profileToProfile(image, lab, srgb, outputMode="RGB")
    image.save(source, icc_profile=lab.tobytes())
    original_bytes = source.read_bytes()
    case = CasePaths(create_case(tmp_path, source, "Restore", {}).case_id, tmp_path)
    with Image.open(case.path("input/canonical.png")) as canonical:
        assert canonical.mode == "RGB" and canonical.tobytes() == expected.tobytes()
        assert canonical.info == {}
    assert case.path("input/original.tiff").read_bytes() == original_bytes == source.read_bytes()

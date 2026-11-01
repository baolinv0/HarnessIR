"""Explicit SDR color audit. No RAW input, resizing, or source-color restoration.

Only audited RGB8 JPEG/PNG and noninterlaced RGB16 PNG are supported. Reuse the
baseline's exact RGB16 decoder and transfer functions, not its permissive loader.
"""
from io import BytesIO
from pathlib import Path
import struct
import zlib

import numpy as np
from PIL import Image, ImageOps, __version__ as PILLOW_VERSION

from hre.models import sha256_bytes
from hre.paths import safe_path
from hre.reference_style.color import (
    MAX_PIXELS, SRGB_MATRIX, P3_MATRIX, SRGB_WHITE,
    linearize, encode_srgb, srgb_profile, read_png16, _is_srgb, _is_display_p3, _chunks,
)
from .contracts import require, exact, content_hash


def pixel_hash(array):
    array = np.ascontiguousarray(array)
    header = dict(version='shape_dtype_bytes_v1', shape=list(array.shape), dtype=array.dtype.str)
    return sha256_bytes(bytes.fromhex(content_hash(header)) + array.tobytes())


def validate_spec(spec):
    require(isinstance(spec,dict), 'input specification must be an object')
    exact(spec, ('role', 'path', 'encoding', 'encoding_basis', 'base_model_version', 'display_assumption')+
          (('source_kind',) if 'source_kind' in spec else ()))
    require(spec['role'] in ('A', 'B'), 'only A/B inputs are allowed')
    kind=spec.get('source_kind','base_model_output' if spec['role']=='A' else 'camera_rgb')
    require(kind in ('base_model_output','camera_rgb'), 'unsupported input source_kind')
    require(spec['encoding'] in ('srgb', 'display_p3', 'unknown'), 'unsupported encoding')
    require(isinstance(spec['encoding_basis'], str) and bool(spec['encoding_basis'].strip()), 'encoding basis required')
    require(isinstance(spec['path'], str), 'path required')
    if spec['role'] == 'A' and kind == 'base_model_output':
        require(isinstance(spec['base_model_version'], str) and bool(spec['base_model_version'].strip()), 'A Base output version required')
    else:
        require(spec['base_model_version'] is None, 'camera_rgb cannot claim a Base model version')
    if spec['role'] == 'B':
        require(kind == 'camera_rgb' and spec['encoding'] == 'srgb', 'B must be known phone sRGB, not Base output')
    if spec['encoding'] == 'unknown':
        require(spec['display_assumption'] == 'srgb', 'unknown A requires explicit visual-only sRGB display assumption')
    else:
        require(spec['display_assumption'] is None, 'known encoding cannot carry display assumption')
    return kind


def _png_color_metadata(raw, encoding):
    """Inspect container metadata, including chunks Pillow may not expose.

    No new color conversion: only consistent SDR sRGB/P3 declarations are admitted.
    tRNS is transparency even when the decoded mode is RGB, at either depth.
    """
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return None
    relevant = {}
    for tag, body in _chunks(raw):
        require(tag != b'tRNS', 'PNG transparency key unsupported; opaque-only input')
        require(tag not in (b'mDCV', b'cLLI', b'acTL'), 'HDR or animated PNG metadata unsupported')
        if tag in (b'cHRM', b'cICP', b'gAMA', b'sRGB', b'iCCP'):
            require(tag not in relevant, 'duplicate PNG color metadata chunk')
            relevant[tag] = body
    observed = {}
    if b'iCCP' in relevant:
        body = relevant[b'iCCP']
        separator = body.find(b'\0')
        require(1 <= separator <= 79 and len(body) > separator + 2,
                'invalid PNG iCCP name or missing compressed profile')
        require(body[separator + 1] == 0, 'unsupported PNG iCCP compression method')
        decoder = zlib.decompressobj()
        try:
            profile = decoder.decompress(body[separator + 2:], 4_000_001)
        except zlib.error as exc:
            raise ValueError('malformed compressed PNG iCCP profile') from exc
        require(132 <= len(profile) <= 4_000_000 and decoder.eof
                and not decoder.unconsumed_tail and not decoder.unused_data,
                'empty, truncated, oversized or trailing PNG iCCP data')
        require(struct.unpack('>I', profile[:4])[0] == len(profile)
                and profile[36:40] == b'acsp', 'invalid embedded ICC header/size')
        try:
            if encoding == 'display_p3':
                _is_display_p3(profile)
            else:
                _is_srgb(profile)
        except (ValueError, struct.error, IndexError) as exc:
            raise ValueError('embedded PNG ICC is unsupported or conflicts with declared encoding') from exc
        observed['iCCP_profile_hash'] = sha256_bytes(profile)
        observed['iCCP_profile_bytes'] = len(profile)
    if b'cHRM' in relevant:
        require(len(relevant[b'cHRM']) == 32, 'invalid PNG chromaticities')
        values = list(struct.unpack('>8I', relevant[b'cHRM']))
        expected = ([31270, 32900, 68000, 32000, 26500, 69000, 15000, 6000]
                    if encoding == 'display_p3' else [31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000])
        require(values == expected, 'PNG chromaticities conflict with declared/assumed encoding')
        observed['cHRM'] = values
    if b'cICP' in relevant:
        values = list(relevant[b'cICP'])
        expected = [12 if encoding == 'display_p3' else 1, 13, 0, 1]
        require(values == expected, 'unsupported or conflicting PNG cICP; SDR full-range RGB required')
        observed['cICP'] = values
    for tag in (b'gAMA', b'sRGB', b'iCCP'):
        if tag in relevant:
            observed[tag.decode('ascii') + '_chunk_hash'] = sha256_bytes(relevant[tag])
    observed['transparency'] = 'absent'
    observed['validation'] = 'consistent_supported_SDR_metadata'
    return observed


def audit_image(spec, out):
    kind=validate_spec(spec)
    result,pixels=_audit_rgb(spec,out)
    result['source_kind']=kind
    if kind=='camera_rgb':result['base_provenance']='not_applicable_camera_rgb'
    return result,pixels


def _audit_rgb(spec, out):
    """Shared conversion after a role-specific caller has validated its contract."""
    source = Path(spec['path']).absolute()
    safe_path(source.parent, source.name, must_exist=True)
    require(source.is_file(), 'input must be a regular file')
    raw = source.read_bytes()
    require(len(raw) <= 512 * 1024 * 1024, 'file size limit')
    png_metadata = _png_color_metadata(raw, spec['encoding'])
    with Image.open(BytesIO(raw)) as image:
        require(image.format in ('PNG', 'JPEG'), 'only SDR PNG/JPEG supported')
        require(getattr(image, 'n_frames', 1) == 1, 'multiple frames unsupported')
        require(0 < image.width * image.height <= MAX_PIXELS, 'pixel limit')
        require(image.mode == 'RGB', 'only opaque RGB input; no implicit conversion')
        native_size = list(image.size)
        orientation = image.getexif().get(274, 1)
        require(type(orientation) is int and 1 <= orientation <= 8, 'invalid EXIF orientation')
        profile = image.info.get('icc_profile')
        if png_metadata is not None and 'iCCP_profile_hash' in png_metadata:
            require(isinstance(profile, bytes) and sha256_bytes(profile) == png_metadata['iCCP_profile_hash'],
                    'PNG iCCP present but decoder ICC metadata is missing or inconsistent')
        srgb_tag = 'srgb' in image.info
        gamma = image.info.get('gamma')
        high = raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw) >= 29 and raw[24] == 16
        if raw.startswith(b'\x89PNG\r\n\x1a\n'):
            require(raw[24] in (8, 16) and raw[25] == 2, 'unsupported PNG bit depth or color type')
        if profile:
            try:
                if spec['encoding'] == 'display_p3':
                    _is_display_p3(profile)
                else:
                    _is_srgb(profile)
            except (ValueError, struct.error, IndexError) as exc:
                raise ValueError('profile unknown or conflicts with declared encoding') from exc
        require(not (srgb_tag and spec['encoding'] == 'display_p3'), 'sRGB tag conflicts with Display P3')
        require(gamma is None or abs(gamma - 0.45455) < 0.0001,
                'non-sRGB PNG gamma requires a separately verified conversion')
        if high:
            require(orientation == 1, 'RGB16 EXIF orientation unsupported; no silent conversion')
            # Read from the captured snapshot, never reopen a possibly changed source.
            native = None
        else:
            native = np.asarray(image, dtype=np.uint8).copy()
            oriented = np.asarray(ImageOps.exif_transpose(image), dtype=np.uint8).copy()
            rgb = oriented.astype(np.float64) / 255
        image_format = image.format

    out = Path(out).absolute()
    safe_path(out.parent, out.name)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'source.bin').write_bytes(raw)
    if high:
        rgb, _ = read_png16(out / 'source.bin')
        native = np.rint(rgb * 65535).astype('<u2')
    source_encoding = spec['encoding']
    working = linearize(rgb)
    if source_encoding == 'display_p3':
        xyz = working @ np.asarray(P3_MATRIX).T
        linear_rgb = xyz @ np.linalg.inv(np.asarray(SRGB_MATRIX)).T
    else:
        linear_rgb = working
        xyz = working @ np.asarray(SRGB_MATRIX).T
    analysis = None
    if source_encoding != 'unknown':
        white_normalized = xyz / np.asarray(SRGB_WHITE)
        delta = 6 / 29
        f = np.where(white_normalized > delta ** 3, np.cbrt(white_normalized),
                     white_normalized / (3 * delta * delta) + 4 / 29)
        lab = np.stack((116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                        200 * (f[..., 1] - f[..., 2])), axis=-1)
        analysis = dict(linear_srgb=linear_rgb, XYZ_D65=xyz,
                        Y=linear_rgb @ np.array([0.2126, 0.7152, 0.0722]),
                        Lab_D65=lab, chroma=np.linalg.norm(lab[..., 1:], axis=-1))
        require(all(np.isfinite(v).all() for v in analysis.values()), 'nonfinite analysis')
        np.savez(out / 'analysis.npz', **analysis)
    encoded = encode_srgb(linear_rgb)
    clipped = np.any((encoded < 0) | (encoded > 1), axis=-1)
    derivative = np.rint(np.clip(encoded, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(derivative).save(out / 'input.png', icc_profile=srgb_profile())
    clip_fraction = float(clipped.mean())
    result = dict(
        role=spec['role'], source_file_hash=sha256_bytes(raw), source_path='source.bin',
        source_pixel_hash=pixel_hash(native), pixel_hash_version='shape_dtype_bytes_v1',
        source_encoding=source_encoding, encoding_basis=spec['encoding_basis'],
        encoding_evidence='explicit_declaration_and_profile_consistency_check',
        base_model_version=spec.get('base_model_version'), base_provenance='caller_declared_not_independently_verified',
        source_format=image_format, source_bit_depth=16 if high else 8,
        source_icc_hash=sha256_bytes(profile) if profile else None,
        source_srgb_tag=srgb_tag, source_gamma=gamma,
        source_png_color_metadata=png_metadata,
        orientation=orientation, native_size=native_size,
        oriented_size=[rgb.shape[1], rgb.shape[0]],
        geometry={'exif_orientation_applied': orientation, 'resize': None, 'crop': None},
        numeric_status='blocked_unknown_encoding' if source_encoding == 'unknown' else 'eligible',
        display_assumption=spec['display_assumption'],
        analysis_version='float64_XYZ_D65_linear_srgb_Lab_D65_v1',
        analysis_path='analysis.npz' if analysis is not None else None,
        analysis_file_hash=sha256_bytes((out / 'analysis.npz').read_bytes()) if analysis is not None else None,
        derivative_path='input.png', derivative_encoding='srgb', derivative_bit_depth=8,
        derivative_file_hash=sha256_bytes((out / 'input.png').read_bytes()),
        derivative_pixel_hash=pixel_hash(derivative),
        conversion_chain=[source_encoding if source_encoding != 'unknown' else 'assumed_srgb_visual_only',
                          'sRGB_piecewise_transfer_decode', 'D65_matrix_to_linear_srgb',
                          'sRGB_piecewise_transfer_encode', 'explicit_endpoint_clip', 'round_to_RGB8'],
        converter={'implementation': 'reference_style_audit_v1', 'numpy': np.__version__, 'pillow': PILLOW_VERSION},
        gamut_clipped_pixel_fraction=clip_fraction,
        critical_color_judgment_requires_review=clip_fraction > 0,
        source_endpoint_pixel_fraction=float(np.any((rgb == 0) | (rgb == 1), axis=-1).mean()),
        quantization=('native RGB16 normalized by 65535; explicit round to RGB8; no precision restoration'
                      if high else 'native RGB8; explicit round to RGB8; no precision restoration'),
    )
    return result, analysis

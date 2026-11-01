"""Deterministic display-domain statistics for canonical RGB8 sRGB images."""
from pathlib import Path
import numpy as np
from PIL import Image

METRIC_VERSION = 'display_stats_v1'


def _pixels(asset: dict, case_root: Path | None) -> np.ndarray:
    from .assets import validate_asset
    from .paths import safe_path
    from .models import HREError
    root = Path(case_root or '.')
    validate_asset(asset, root)
    if asset.get('color_space') != 'sRGB':
        raise HREError('invalid_color_space', 'statistics require canonical sRGB')
    with Image.open(safe_path(root, asset['path'], must_exist=True)) as image:
        if image.mode != 'RGB':
            raise HREError('invalid_image_mode', 'statistics require canonical RGB8')
        return np.asarray(image, dtype=np.float64) / 255.0


def _metrics(pixels: np.ndarray) -> dict:
    from .models import HREError
    rgb = np.asarray(pixels, dtype=np.float64).reshape(-1, 3)
    if not len(rgb):
        raise HREError('empty_roi', 'empty ROI is unavailable')
    luma = rgb @ np.array([.2126, .7152, .0722])
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    xyz = linear @ np.array([[.4124564,.3575761,.1804375], [.2126729,.7151522,.0721750], [.0193339,.1191920,.9503041]]).T
    ratio = xyz / np.array([.95047, 1., 1.08883])
    delta = 6 / 29
    f = np.where(ratio > delta**3, np.cbrt(ratio), ratio/(3*delta**2)+4/29)
    lab = np.column_stack([116*f[:,1]-16, 500*(f[:,0]-f[:,1]), 200*(f[:,1]-f[:,2])])
    high = rgb.max(axis=1); low = rgb.min(axis=1)
    sat = np.divide(high-low, high, out=np.zeros_like(high), where=high != 0)
    return dict(mean_luma=float(luma.mean()), p10_luma=float(np.quantile(luma,.1,method='linear')),
                p50_luma=float(np.quantile(luma,.5,method='linear')),p90_luma=float(np.quantile(luma,.9,method='linear')),
                shadow_fraction=float((luma < .1).mean()), highlight_fraction=float((luma > .95).mean()),
                mean_rgb=rgb.mean(axis=0).tolist(), mean_lab=lab.mean(axis=0).tolist(), mean_saturation=float(sat.mean()))


def compute_stats(asset: dict, mask_path: Path | None = None, *, case_root: Path | None = None) -> dict:
    """Return schema payload; an empty validity mask raises empty_roi, never zero metrics."""
    from .models import HREError, file_sha256
    from .paths import safe_path
    rgb = _pixels(asset, case_root)
    mask_sha = None
    if mask_path is not None:
        path = Path(mask_path)
        if case_root is not None:
            try:
                relative = path.relative_to(Path(case_root)) if path.is_absolute() else path
            except ValueError as exc:
                raise HREError('unsafe_path','mask outside case root') from exc
            path = safe_path(Path(case_root), relative.as_posix(), must_exist=True)
        if path.suffix.lower() == '.npy':
            mask = np.load(path, allow_pickle=False)
        else:
            with Image.open(path) as image:
                mask = np.asarray(image)
        if mask.shape != rgb.shape[:2]:
            raise HREError('mask_shape', 'mask shape must equal canonical image dimensions')
        if not np.isfinite(mask).all():
            raise HREError('invalid_mask', 'mask values must be finite')
        rgb = rgb[mask != 0]
        mask_sha = file_sha256(path)
    count = int(rgb.size // 3)
    return {'metric_version': METRIC_VERSION, 'regions': [dict(region_id='masked' if mask_path else 'full',
        source_asset_id=asset['asset_id'],mask_sha256=mask_sha,sample_count=count,metrics=_metrics(rgb))]}

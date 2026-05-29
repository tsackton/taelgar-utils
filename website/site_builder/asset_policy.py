from __future__ import annotations

import fnmatch
import math
import warnings
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any

from .notes import IMAGE_SUFFIXES


OPTIMIZABLE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class TileBounds:
    y0: float
    x0: float
    y1: float
    x1: float

    @property
    def width(self) -> int:
        return max(1, ceil(abs(self.x1 - self.x0)))

    @property
    def height(self) -> int:
        return max(1, ceil(abs(self.y1 - self.y0)))


def asset_target_path_for(source_path: Path, relative_path: Path, target_path: Path, config: Any) -> Path:
    if should_convert_to_webp(source_path, relative_path, config):
        return target_path.with_suffix(".webp")
    return target_path


def should_convert_to_webp(source_path: Path, relative_path: Path, config: Any) -> bool:
    suffix = source_path.suffix.lower()
    return bool(
        config.resize_images
        and config.optimize_images
        and suffix in OPTIMIZABLE_IMAGE_SUFFIXES
        and not is_resize_excluded_path(relative_path, config)
        and not image_has_transparency(source_path)
    )


def is_resize_excluded_path(relative_path: Path, config: Any) -> bool:
    relative = relative_path.as_posix()
    filename = relative_path.name
    return any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(filename, pattern) for pattern in config.resize_exclude_assets)


def image_has_transparency(source_path: Path) -> bool:
    if source_path.suffix.lower() not in IMAGE_SUFFIXES:
        return False
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(source_path) as img:
                if img.mode in {"RGBA", "LA"}:
                    return True
                if img.mode == "P" and "transparency" in img.info:
                    return True
    except OSError:
        return False
    return False


def is_tile_map_asset(relative_path: Path, config: Any) -> bool:
    relative = relative_path.as_posix()
    filename = relative_path.name
    return any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(filename, pattern) for pattern in config.tile_map_assets)


def parse_tile_bounds(value: object) -> TileBounds | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    try:
        start, end = value
        y0, x0 = start
        y1, x1 = end
        return TileBounds(float(y0), float(x0), float(y1), float(x1))
    except (TypeError, ValueError):
        return None


def image_tile_bounds(source_path: Path) -> TileBounds | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(source_path) as img:
                width, height = img.size
    except OSError:
        return None
    return TileBounds(0, 0, height, width)


def tile_native_max_zoom(source_path: Path, bounds: TileBounds) -> int:
    try:
        from PIL import Image
    except ImportError:
        return 0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(source_path) as img:
                source_width, source_height = img.size
    except OSError:
        return 0
    ratio = max(source_width / bounds.width, source_height / bounds.height, 1)
    return max(0, math.ceil(math.log2(ratio)))


def tile_base_path(target_path: Path) -> Path:
    stem = target_path.with_suffix("").name
    return Path("assets") / "tiles" / stem


def tile_extension(config: Any) -> str:
    return "jpg" if config.map_tile_format == "jpeg" else str(config.map_tile_format)


def tile_url_template(target_path: Path, config: Any) -> Path:
    return tile_base_path(target_path) / "{z}" / "{x}" / ("{y}." + tile_extension(config))


def tile_paths(target_path: Path, bounds: TileBounds, config: Any, source_path: Path | None = None) -> list[Path]:
    size = config.map_tile_size
    native_max_zoom = tile_native_max_zoom(source_path, bounds) if source_path else 0
    base = tile_base_path(target_path)
    extension = tile_extension(config)
    paths: list[Path] = []
    for zoom in range(native_max_zoom + 1):
        scale = 2**zoom
        x_count = ceil(bounds.width * scale / size)
        y_count = ceil(bounds.height * scale / size)
        zoom_base = base / str(zoom)
        paths.extend(zoom_base / str(x) / f"{y}.{extension}" for x in range(x_count) for y in range(y_count))
    return paths

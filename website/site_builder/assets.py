from __future__ import annotations

import fnmatch
import shutil
import threading
import warnings
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any

from .asset_policy import TileBounds, is_resize_excluded_path, tile_native_max_zoom
from .notes import IMAGE_SUFFIXES
from .scanner import SourceEntry

WEBP_METHOD = 2
_WARNING_LOCK = threading.Lock()


@dataclass
class AssetCopyResult:
    copied: bool
    resized: bool
    optimized: bool = False


def copy_asset(entry: SourceEntry, target_path: Path, config: Any) -> AssetCopyResult:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = entry.source_path.suffix.lower()
    if config.resize_images and suffix in IMAGE_SUFFIXES - {".gif", ".heic"} and not is_resize_excluded(entry, config):
        try:
            from PIL import Image
        except ImportError as error:
            raise RuntimeError("resize_images requires Pillow to be installed") from error
        with _WARNING_LOCK:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", Image.DecompressionBombWarning)
                img = Image.open(entry.source_path)
        for warning in caught:
            if issubclass(warning.category, Image.DecompressionBombWarning):
                warnings.warn(
                    f"{entry.source_path}: {warning.message}",
                    Image.DecompressionBombWarning,
                    stacklevel=2,
                )
        with img:
            img.load()
            width, height = img.size
            resized = False
            if width > config.max_image_width or height > config.max_image_height:
                ratio = min(config.max_image_width / width, config.max_image_height / height)
                new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
                resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                img = img.resize(new_size, resampling)
                resized = True
            if target_path.suffix.lower() == ".webp":
                img = img.convert("RGB")
                img.save(target_path, "WEBP", quality=config.webp_quality, method=WEBP_METHOD)
                return AssetCopyResult(copied=True, resized=resized, optimized=True)
            if resized:
                img.save(target_path)
                return AssetCopyResult(copied=True, resized=True)
    shutil.copy2(entry.source_path, target_path)
    return AssetCopyResult(copied=True, resized=False)


def is_resize_excluded(entry: SourceEntry, config: Any) -> bool:
    return is_resize_excluded_path(entry.relative_path, config)


@dataclass
class TileGenerationResult:
    generated: bool
    paths: list[Path]
    tiles_written: int
    bytes_written: int


def generate_map_tiles(entry: SourceEntry, docs_dir: Path, bounds: TileBounds, config: Any) -> TileGenerationResult:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("map tiling requires Pillow to be installed") from error

    from .asset_policy import tile_paths

    relative_paths = tile_paths(entry.target_path, bounds, config, entry.source_path)
    target_paths = [docs_dir / path for path in relative_paths]
    for target in target_paths:
        target.parent.mkdir(parents=True, exist_ok=True)

    native_max_zoom = tile_native_max_zoom(entry.source_path, bounds)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(entry.source_path) as img:
            img.load()
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            source_image = img.convert("RGB")

    tile_size = config.map_tile_size
    bytes_written = 0
    tiles_written = 0
    with source_image:
        for zoom in range(native_max_zoom + 1):
            scale = 2**zoom
            display_width = bounds.width * scale
            display_height = bounds.height * scale
            display = source_image.resize((display_width, display_height), resampling)
            x_count = ceil(display_width / tile_size)
            y_count = ceil(display_height / tile_size)
            y_padding = y_count * tile_size - display_height
            with display:
                for x in range(x_count):
                    for y in range(y_count):
                        left = x * tile_size
                        source_upper = y * tile_size - y_padding
                        source_lower = source_upper + tile_size
                        crop_box = (
                            left,
                            max(0, source_upper),
                            min(left + tile_size, display_width),
                            min(source_lower, display_height),
                        )
                        crop = display.crop(crop_box)
                        tile = Image.new("RGB", (tile_size, tile_size), "white")
                        tile.paste(crop, (0, max(0, -source_upper)))
                        target = docs_dir / relative_paths[tiles_written]
                        if config.map_tile_format == "webp":
                            tile.save(target, "WEBP", quality=config.map_tile_quality, method=WEBP_METHOD)
                        elif config.map_tile_format in {"jpg", "jpeg"}:
                            tile.save(target, "JPEG", quality=config.map_tile_quality)
                        else:
                            tile.save(target, "PNG")
                        bytes_written += target.stat().st_size
                        tiles_written += 1

    return TileGenerationResult(generated=True, paths=relative_paths, tiles_written=tiles_written, bytes_written=bytes_written)


def copy_tree_contents(source: Path, dest: Path) -> list[Path]:
    copied: list[Path] = []
    if not source.exists():
        return copied
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        target = dest / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied.append(target)
    return copied

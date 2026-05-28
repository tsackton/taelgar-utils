from __future__ import annotations

import fnmatch
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .notes import IMAGE_SUFFIXES
from .scanner import SourceEntry


@dataclass
class AssetCopyResult:
    copied: bool
    resized: bool


def copy_asset(entry: SourceEntry, target_path: Path, config: Any) -> AssetCopyResult:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = entry.source_path.suffix.lower()
    if config.resize_images and suffix in IMAGE_SUFFIXES - {".gif", ".heic"} and not is_resize_excluded(entry, config):
        try:
            from PIL import Image
        except ImportError as error:
            raise RuntimeError("resize_images requires Pillow to be installed") from error
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
            width, height = img.size
            if width > config.max_image_width or height > config.max_image_height:
                ratio = min(config.max_image_width / width, config.max_image_height / height)
                new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
                resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                img = img.resize(new_size, resampling)
                img.save(target_path)
                return AssetCopyResult(copied=True, resized=True)
    shutil.copy2(entry.source_path, target_path)
    return AssetCopyResult(copied=True, resized=False)


def is_resize_excluded(entry: SourceEntry, config: Any) -> bool:
    relative_path = entry.relative_path.as_posix()
    filename = entry.relative_path.name
    return any(fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(filename, pattern) for pattern in config.resize_exclude_assets)


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

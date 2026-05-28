from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


ALLOWED_KEYS = {
    "source_dir",
    "docs_dir",
    "overrides_source",
    "overrides_dir",
    "slugify",
    "clean_docs",
    "campaigns",
    "export_date",
    "strip_comments",
    "strip_campaign_blocks",
    "strip_date_blocks",
    "clean_inline_tags",
    "home_source",
    "home_dest",
    "nav_source",
    "nav_dest",
    "ignore_file",
    "asset_dir",
    "resize_images",
    "resize_exclude_assets",
    "max_image_width",
    "max_image_height",
    "delete_unlinked_assets",
    "base_path",
    "clean_code_blocks",
    "codeblock_template_dir",
    "hide_toc_tags",
    "hide_nav_tags",
    "hide_backlinks_tags",
    "unnamed_files",
    "stub_files",
    "skip_future_dated",
    "always_include_assets",
    "manifest_path",
}


@dataclass(frozen=True)
class WebsiteConfig:
    root_dir: Path
    config_path: Path
    source_dir: Path
    docs_dir: Path
    overrides_source: Path | None = None
    overrides_dir: Path | None = None
    slugify: bool = True
    clean_docs: bool = False
    campaigns: tuple[str, ...] = ()
    export_date: str | None = None
    strip_comments: bool = True
    strip_campaign_blocks: bool = True
    strip_date_blocks: bool = True
    clean_inline_tags: bool = True
    home_source: Path | None = None
    home_dest: Path = Path("index.md")
    nav_source: Path | None = None
    nav_dest: Path = Path("toc.md")
    ignore_file: Path | None = None
    asset_dir: Path = Path("assets")
    resize_images: bool = False
    resize_exclude_assets: tuple[str, ...] = ()
    max_image_width: int = 1600
    max_image_height: int = 1600
    delete_unlinked_assets: bool = True
    base_path: str = "/"
    clean_code_blocks: bool = True
    codeblock_template_dir: Path | None = None
    hide_toc_tags: tuple[str, ...] = ()
    hide_nav_tags: tuple[str, ...] = ()
    hide_backlinks_tags: tuple[str, ...] = ()
    unnamed_files: str = "unlist"
    stub_files: str = "skip"
    skip_future_dated: bool = True
    always_include_assets: tuple[str, ...] = ()
    manifest_path: Path = Path(".website-build/export-manifest.json")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "slugify": self.slugify,
            "campaigns": self.campaigns,
            "export_date": self.export_date,
            "strip_comments": self.strip_comments,
            "strip_campaign_blocks": self.strip_campaign_blocks,
            "strip_date_blocks": self.strip_date_blocks,
            "clean_inline_tags": self.clean_inline_tags,
            "base_path": self.base_path,
            "clean_code_blocks": self.clean_code_blocks,
            "codeblock_template_dir": str(self.codeblock_template_dir) if self.codeblock_template_dir else None,
            "hide_toc_tags": self.hide_toc_tags,
            "hide_nav_tags": self.hide_nav_tags,
            "hide_backlinks_tags": self.hide_backlinks_tags,
            "unnamed_files": self.unnamed_files,
            "stub_files": self.stub_files,
            "skip_future_dated": self.skip_future_dated,
            "resize_images": self.resize_images,
            "resize_exclude_assets": self.resize_exclude_assets,
            "max_image_width": self.max_image_width,
            "max_image_height": self.max_image_height,
        }


def load_config(config_path: str | Path = "website.json") -> WebsiteConfig:
    path = Path(config_path).resolve()
    root_dir = path.parent
    raw = json.loads(path.read_text(encoding="utf-8"))
    unknown = sorted(set(raw) - ALLOWED_KEYS)
    if unknown:
        raise ConfigError(f"Unknown website.json key(s): {', '.join(unknown)}")

    def path_value(key: str, default: str | None = None) -> Path | None:
        value = raw.get(key, default)
        if value in (None, ""):
            return None
        candidate = Path(value)
        return candidate if candidate.is_absolute() else root_dir / candidate

    def relative_path_value(key: str, default: str) -> Path:
        value = raw.get(key, default)
        candidate = Path(value)
        if candidate.is_absolute():
            raise ConfigError(f"{key} must be relative to docs_dir")
        return candidate

    def bool_value(key: str, default: bool) -> bool:
        value = raw.get(key, default)
        if not isinstance(value, bool):
            raise ConfigError(f"{key} must be true or false")
        return value

    def int_value(key: str, default: int) -> int:
        value = raw.get(key, default)
        if not isinstance(value, int) or value <= 0:
            raise ConfigError(f"{key} must be a positive integer")
        return value

    def string_tuple(key: str) -> tuple[str, ...]:
        value = raw.get(key, [])
        if value is None:
            return ()
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigError(f"{key} must be a list of strings")
        return tuple(value)

    source_dir = path_value("source_dir")
    docs_dir = path_value("docs_dir")
    if source_dir is None:
        raise ConfigError("source_dir is required")
    if docs_dir is None:
        raise ConfigError("docs_dir is required")

    unnamed_files = raw.get("unnamed_files", "unlist")
    stub_files = raw.get("stub_files", "skip")
    for key, value in {"unnamed_files": unnamed_files, "stub_files": stub_files}.items():
        if value not in {"skip", "unlist", "include"}:
            raise ConfigError(f"{key} must be one of: skip, unlist, include")

    base_path = raw.get("base_path", "/")
    if not isinstance(base_path, str):
        raise ConfigError("base_path must be a string")
    if base_path and not base_path.endswith("/"):
        base_path += "/"

    return WebsiteConfig(
        root_dir=root_dir,
        config_path=path,
        source_dir=source_dir,
        docs_dir=docs_dir,
        overrides_source=path_value("overrides_source"),
        overrides_dir=path_value("overrides_dir"),
        slugify=bool_value("slugify", True),
        clean_docs=bool_value("clean_docs", False),
        campaigns=string_tuple("campaigns"),
        export_date=raw.get("export_date"),
        strip_comments=bool_value("strip_comments", True),
        strip_campaign_blocks=bool_value("strip_campaign_blocks", True),
        strip_date_blocks=bool_value("strip_date_blocks", True),
        clean_inline_tags=bool_value("clean_inline_tags", True),
        home_source=path_value("home_source"),
        home_dest=relative_path_value("home_dest", "index.md"),
        nav_source=path_value("nav_source"),
        nav_dest=relative_path_value("nav_dest", "toc.md"),
        ignore_file=path_value("ignore_file"),
        asset_dir=relative_path_value("asset_dir", "assets"),
        resize_images=bool_value("resize_images", False),
        resize_exclude_assets=string_tuple("resize_exclude_assets"),
        max_image_width=int_value("max_image_width", 1600),
        max_image_height=int_value("max_image_height", 1600),
        delete_unlinked_assets=bool_value("delete_unlinked_assets", True),
        base_path=base_path,
        clean_code_blocks=bool_value("clean_code_blocks", True),
        codeblock_template_dir=path_value("codeblock_template_dir"),
        hide_toc_tags=string_tuple("hide_toc_tags"),
        hide_nav_tags=string_tuple("hide_nav_tags"),
        hide_backlinks_tags=string_tuple("hide_backlinks_tags"),
        unnamed_files=unnamed_files,
        stub_files=stub_files,
        skip_future_dated=bool_value("skip_future_dated", True),
        always_include_assets=string_tuple("always_include_assets"),
        manifest_path=path_value("manifest_path", ".website-build/export-manifest.json") or root_dir
        / ".website-build/export-manifest.json",
    )

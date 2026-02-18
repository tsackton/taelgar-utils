#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import re

from dotenv import load_dotenv

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".yml", ".yaml"):
        if yaml is None:
            raise RuntimeError(
                "PyYAML is required to load YAML configs. Install with: pip install pyyaml"
            )
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    elif suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise ValueError(f"Unsupported config file extension: {suffix}")


def build_command(config: dict, token: str, output_path: Path, assets_dir: Path) -> list[str]:
    """
    Build the DiscordChatExporter CLI command.

    - Uses `--media` + `--media-dir` so assets are downloaded locally.
    - If format is Json, also sets `--markdown false` for raw content.
    """
    exe = config.get("executable_path")
    if not exe:
        raise ValueError("Config must contain 'executable_path'")

    channel_id = config.get("channel_id")
    if not channel_id:
        raise ValueError("Config must contain 'channel_id'")

    fmt = config.get("format", "Json")
    last_date = config.get("last_retrieved_date") or ""

    cmd = [
        exe,
        "export",           # works for channels/DMs when using -c
        "-t", token,
        "-c", str(channel_id),
        "-o", str(output_path),
        "-f", fmt,
        "--media",          # download attachments/assets
        "--media-dir", str(assets_dir),
    ]

    # For JSON exports, request raw content instead of preformatted markdown
    if fmt.lower() == "json":
        cmd.extend(["--markdown", "false"])

    if last_date.strip():
        # Only export messages after this date
        cmd.extend(["--after", last_date.strip()])

    return cmd


def parse_iso_timestamp(value: str) -> datetime:
    # DiscordChatExporter uses ISO timestamps; fromisoformat handles offsets.
    # Some exports may have 'Z' for UTC, so normalize that.
    v = value.replace("Z", "+00:00")
    return datetime.fromisoformat(v)


def convert_json_to_daily_markdown(
    json_path: Path,
    md_dir: Path,
    assets_dir: Path,
    full_export: bool,
    asset_path_replacement: str | None = None,
) -> None:
    """
    Read a DiscordChatExporter JSON export and write per-day markdown
    files into md_dir. Attachments are linked relative to md_dir, assuming
    media files live under assets_dir.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"JSON export not found at {json_path}")

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("Messages") or data.get("messages")
    if messages is None:
        raise ValueError("JSON export does not contain a 'Messages' array")

    md_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Group messages by local calendar date
    messages_by_date: dict[datetime.date, list[dict]] = {}
    for msg in messages:
        ts_raw = msg.get("Timestamp") or msg.get("timestamp")
        if not ts_raw:
            continue

        try:
            dt = parse_iso_timestamp(ts_raw)
        except Exception:
            continue

        local_dt = dt.astimezone()  # local time for grouping & display
        day = local_dt.date()

        msg["_local_datetime"] = local_dt  # stash for later formatting
        messages_by_date.setdefault(day, []).append(msg)

    if not messages_by_date:
        print("No messages found in JSON to convert to markdown.")
        return

    # Sort dates and messages within each day
    for day, mlist in messages_by_date.items():
        mlist.sort(key=lambda m: m["_local_datetime"])
    days_sorted = sorted(messages_by_date.keys())

    # Determine write mode based on whether this is a fresh/full export
    # - full_export: overwrite any existing daily files
    # - incremental: append to existing files
    for day in days_sorted:
        day_msgs = messages_by_date[day]
        day_str = day.isoformat()
        md_file = md_dir / f"{day_str}.md"

        mode = "w" if full_export else ("a" if md_file.exists() else "w")

        with md_file.open(mode, encoding="utf-8") as out:
            if mode == "a":
                out.write("\n")  # blank line before new block

            # Simple heading per file (only once, at the top)
            if mode == "w":
                out.write(f"# Discord DM – {day_str}\n\n")

            for msg in day_msgs:
                local_dt = msg["_local_datetime"]
                timestamp_str = local_dt.strftime("%Y-%m-%d %I:%M %p")

                author = msg.get("Author") or msg.get("author") or {}
                author_name = next(
                    (
                        value
                        for value in (
                            author.get("Nickname"),
                            author.get("nickname"),
                            author.get("Name"),
                            author.get("name"),
                            author.get("Username"),
                            author.get("username"),
                            author.get("DisplayName"),
                            author.get("displayName"),
                            author.get("Id"),
                            author.get("id"),
                        )
                        if value
                    ),
                    "Unknown",
                )

                content_raw = msg.get("Content") or msg.get("content") or ""

                def _escape_asterisk_prefix(match: re.Match[str]) -> str:
                    leading = match.group(1)
                    rest = match.group(2)
                    # Only escape if the word does not end with the same leading character
                    if rest.endswith(leading[-1]):
                        return match.group(0)
                    return f"`{leading}`{rest}"

                content = re.sub(r"(?<!\S)(\*{1,3})(\S+)", _escape_asterisk_prefix, content_raw)
                content = content.replace("%%", "`%%`")
                # Escape angle brackets and single square brackets (but keep Obsidian-style [[ ]])
                content = content.replace("<", "`<").replace(">", ">`")
                placeholder_open = "__OB_OPEN__"
                placeholder_close = "__OB_CLOSE__"
                content = content.replace("[[", placeholder_open).replace("]]", placeholder_close)
                content = content.replace("[", "`[").replace("]", "]`")
                content = content.replace(placeholder_open, "[[").replace(placeholder_close, "]]")

                content_lines = content.splitlines() or [""]
                first_line, *rest_lines = content_lines

                prefix = f"[{timestamp_str}] {author_name}: "
                out.write(f"{prefix}{first_line}\n")
                for line in rest_lines:
                    out.write(f"    {line}\n")

                # Attachments: link into assets_dir if possible
                attachments = msg.get("Attachments") or msg.get("attachments") or []
                for att in attachments:
                    # Try to get a local path if DiscordChatExporter stored one
                    # Common patterns: Path/LocalPath + FileName/Filename
                    local_path_str = (
                        att.get("Path")
                        or att.get("LocalPath")
                        or att.get("LocalFileName")
                        or att.get("url")
                        or att.get("Url")
                        or ""
                    )
                    filename = (
                        att.get("FileName")
                        or att.get("Filename")
                        or att.get("fileName")
                        or os.path.basename(local_path_str)
                        or "attachment"
                    )

                    # Compute filesystem path we *think* the asset lives at
                    if local_path_str:
                        # Treat the stored path as relative to the JSON file directory
                        abs_attachment_path = (json_path.parent / local_path_str).resolve()
                    else:
                        abs_attachment_path = (assets_dir / filename).resolve()

                    # Relative path from md_dir to the asset
                    rel_path = os.path.relpath(abs_attachment_path, start=md_dir)
                    if asset_path_replacement:
                        rel_parts = Path(rel_path).parts
                        try:
                            idx = rel_parts.index(assets_dir.name)
                        except ValueError:
                            replaced_rel_path = rel_path
                        else:
                            replaced_rel_path = str(
                                Path(*rel_parts[:idx], asset_path_replacement, *rel_parts[idx + 1 :])
                            )
                        rel_path = replaced_rel_path

                    # Decide whether to embed as image or generic file link
                    ext = Path(filename).suffix.lower().lstrip(".")
                    is_image = ext in {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"}
                    if is_image:
                        out.write(f"![[{rel_path}]]\n")
                    else:
                        try:
                            text = abs_attachment_path.read_text(encoding="utf-8")
                        except FileNotFoundError:
                            text = None
                            out.write(f"[Attachment missing: {filename}]({rel_path})\n")
                        except UnicodeDecodeError:
                            text = None
                            out.write(f"[Attachment: {filename}]({rel_path})\n")
                        else:
                            lang = ext or ""
                            out.write(f"Attachment ({filename}):\n")
                            out.write(f"```{lang}\n{text.rstrip()}\n```\n")

            out.write("\n")

    print(f"Markdown by-day export written to: {md_dir}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Wrapper for DiscordChatExporter using DISCORD_USER from .env.\n"
            "Exports a channel/DM to JSON + media and splits it into per-day markdown files."
        )
    )
    parser.add_argument(
        "--config",
        "-c",
        required=True,
        help="Path to YAML or JSON config file",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to output file (e.g. /path/to/export/worldbuilding_dm.json)",
    )
    parser.add_argument(
        "--reprocess-only",
        action="store_true",
        help="Skip Discord export and re-convert an existing JSON export into markdown.",
    )
    parser.add_argument(
        "--asset-path-replacement",
        help="Override the assets directory name in generated markdown links (markdown-only).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force a full markdown overwrite (do not append to existing daily files).",
    )

    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Directories for markdown and assets live next to the JSON export
    export_root = output_path.parent
    md_dir = export_root / "md"
    assets_dir = export_root / "assets"

    fmt = config.get("format", "Json")
    default_full_export = not bool(config.get("last_retrieved_date"))
    full_export = bool(args.force) or default_full_export
    asset_path_replacement = (
        args.asset_path_replacement
        or config.get("assset_path_replacement")
        or None
    )

    if not args.reprocess_only:
        # Load environment variables
        load_dotenv()
        token = os.getenv("DISCORD_USER")
        if not token:
            print("ERROR: DISCORD_USER not found in environment (.env).", file=sys.stderr)
            sys.exit(1)

        cmd = build_command(config, token, output_path, assets_dir)

        print("Running DiscordChatExporter with command:")
        print("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))

        try:
            completed = subprocess.run(cmd, check=False)
        except FileNotFoundError:
            print(
                f"ERROR: Executable not found: {config.get('executable_path')}",
                file=sys.stderr,
            )
            sys.exit(1)

        if completed.returncode != 0:
            print(
                f"DiscordChatExporter exited with code {completed.returncode}",
                file=sys.stderr,
            )
            sys.exit(completed.returncode)

        print(f"Export completed. Output written to: {output_path}")
    else:
        print("Skipping Discord export; reprocessing existing JSON into markdown.")
        if not output_path.exists():
            print(f"ERROR: JSON export does not exist at {output_path}", file=sys.stderr)
            sys.exit(1)

    # Convert JSON export -> per-day markdown files
    if fmt.lower() == "json":
        try:
            convert_json_to_daily_markdown(
                json_path=output_path,
                md_dir=md_dir,
                assets_dir=assets_dir,
                full_export=full_export,
                asset_path_replacement=asset_path_replacement,
            )
        except Exception as e:
            print(f"WARNING: Failed to convert JSON export to markdown: {e}", file=sys.stderr)
    else:
        print("Skipping markdown conversion because format is not JSON.")

    # Print a completion timestamp for manual config updates
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    print()
    print(f"Processing finished at local time: {stamp}")
    print(
        "If you want incremental exports, set 'last_retrieved_date' in your config "
        f"to this value (or later)."
    )


if __name__ == "__main__":
    main()

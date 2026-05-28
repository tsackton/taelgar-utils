from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .notes import title_case
from .scanner import SourceEntry, note_is_unlisted


@dataclass
class NavResult:
    lines: list[str]
    warnings: list[str] = field(default_factory=list)


class MkDocsNavigationGenerator:
    def __init__(self, template_path: Path, entries: list[SourceEntry], config: Any) -> None:
        self.template_path = template_path
        self.config = config
        self.entries = [entry for entry in entries if entry.is_markdown and entry.note is not None]
        self.metadata_by_path = {entry.target_path.as_posix(): entry.note.metadata for entry in self.entries if entry.note}
        self.warnings: list[str] = []

    @staticmethod
    def count_indentation(line: str) -> int:
        return (len(line) - len(line.lstrip(" "))) // 4

    def process_template(self) -> NavResult:
        processed_lines: list[str] = []
        for line in self.template_path.read_text(encoding="utf-8").splitlines():
            if "{glob:" not in line:
                processed_lines.append(line.rstrip())
                continue
            depth = self.count_indentation(line)
            dir_paths, exclude_files, flatten = parse_glob_line(line)
            generated = self.generate_markdown_list_from_directory(dir_paths, depth, exclude_files, flatten)
            if not generated:
                self.warnings.append(f"Nav glob produced no entries: {line.strip()}")
            processed_lines.extend(generated)
        return NavResult(lines=processed_lines, warnings=self.warnings)

    def generate_markdown_list_from_directory(
        self,
        directory_list: list[Path],
        depth: int = 0,
        exclude_files: set[str] | None = None,
        flatten: bool = False,
    ) -> list[str]:
        exclude_files = exclude_files or set()
        indent = "    " * depth
        lines: list[str] = []
        files: list[SourceEntry] = []
        subdirs: set[Path] = set()

        for directory in directory_list:
            directory = normalize_dir(directory)
            if flatten:
                files.extend([entry for entry in self.entries if is_under(entry.target_path, directory)])
            else:
                files.extend([entry for entry in self.entries if normalize_dir(entry.target_path.parent) == directory])
                for entry in self.entries:
                    parent = normalize_dir(entry.target_path.parent)
                    if parent == directory or not is_under(parent, directory):
                        continue
                    remainder = parent.relative_to(directory)
                    if remainder.parts:
                        subdirs.add(directory / remainder.parts[0])

        visible_files = [
            entry
            for entry in files
            if entry.target_path.name not in exclude_files and entry.note and not note_is_unlisted(entry.note, self.config)
        ]
        for entry in sorted(visible_files, key=lambda item: item.note.page_title.lower() if item.note else ""):
            title = entry.note.page_title if entry.note else entry.target_path.stem
            lines.append(f"{indent}- [{title}]({entry.target_path.as_posix()})")

        if flatten:
            return lines

        for subdir in sorted(subdirs, key=lambda item: item.as_posix().lower()):
            index_file = subdir / f"{subdir.name}.md"
            index_entry = next((entry for entry in self.entries if entry.target_path == index_file), None)
            child_exclude = set(exclude_files)
            subdir_lines: list[str] = []
            if index_entry and index_entry.note and not note_is_unlisted(index_entry.note, self.config):
                title = index_entry.note.page_title
                subdir_lines.append(f"{indent}- [{title}]({index_file.as_posix()})")
                child_exclude.add(index_file.name)
            else:
                title = title_case(subdir.name.replace("-", " "))
                subdir_lines.append(f"{indent}- {title}")
            child_lines = self.generate_markdown_list_from_directory([subdir], depth + 1, child_exclude)
            if child_lines:
                lines.extend(subdir_lines)
                lines.extend(child_lines)
            elif index_entry:
                lines.extend(subdir_lines)
            else:
                self.warnings.append(f"Omitted empty nav directory: {subdir.as_posix()}")
        return lines


def parse_glob_line(line: str) -> tuple[list[Path], set[str], bool]:
    flatten = False
    parts = line.split(",")
    dir_part = parts[0].split("{glob:")[-1].strip().replace("}", "")
    raw_dirs = [part.strip() for part in dir_part.split(";") if part.strip()]
    if "flatten" in raw_dirs:
        flatten = True
    directories = [Path(part) for part in raw_dirs if part != "flatten"]
    exclude_files: set[str] = set()
    for part in parts[1:]:
        if "exclude:" in part:
            exclude_text = part.split("exclude:", 1)[-1].strip().strip("}")
            exclude_files.update(item.strip() for item in exclude_text.split(";") if item.strip())
    return directories, exclude_files, flatten


def normalize_dir(path: Path) -> Path:
    return Path(".") if path.as_posix() in {"", "."} else path


def is_under(path: Path, directory: Path) -> bool:
    path = normalize_dir(path)
    directory = normalize_dir(directory)
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


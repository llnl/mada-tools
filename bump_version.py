#!/usr/bin/env python3
"""
This script helps update the version for this repository.

The files that track version are:
- pyproject.toml
- src/mada_tools/__init__.py
- CHANGELOG.md

Usage:

    ```bash
    # Alpha
    python3 bump_version.py 1.2.3a1

    # Beta
    python3 bump_version.py 1.2.3b1

    # Release Candidate
    python3 bump_version.py 1.2.3rc1

    # Stable Release
    python3 bump_version.py 1.2.3
    ```
"""
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

VERSION_RE = re.compile(r'(?m)^(version\s*=\s*")([^"]+)(")')
INIT_RE = re.compile(r'(?m)^(__version__\s*=\s*")([^"]+)(")')


def update_file(path: Path, pattern: re.Pattern[str], new_version: str) -> bool:
    """
    Update the first version string matched by `pattern` in `path`.

    Args:
        path: File to update.
        pattern: Regular expression used to find the version string.
        new_version: Replacement version string.

    Returns:
        True if a replacement was made, otherwise False.
    """
    text = path.read_text(encoding="utf-8")
    new_text, count = pattern.subn(rf'\g<1>{new_version}\3', text, count=1)
    if count:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def prepend_changelog_section(path: Path, new_version: str) -> None:
    """
    Move the current Unreleased section into a dated release section and insert
    a fresh blank Unreleased section above it.

    Args:
        path: Path to the changelog file.
        new_version: Version string for the new release section.
    """
    today = date.today().isoformat()
    new_header = f"## {new_version} - {today}"

    blank_unreleased = """## Unreleased

### Added
- 

### Changed
- 

### Fixed
- 

"""

    def is_blank_item(line: str) -> bool:
        """
        Return True if `line` is a placeholder bullet or blank line.

        Args:
            line: A single changelog line.

        Returns:
            True if the line is blank or a placeholder item, otherwise False.
        """
        stripped = line.strip()
        return stripped in {"-", "- ", "+", "+ ", "*", "* " ""}

    def build_released_section(unreleased_body: list[str]) -> str:
        """
        Build a released changelog section from the body of Unreleased.

        Empty subsections are removed.

        Args:
            unreleased_body: Lines belonging to the current Unreleased section.

        Returns:
            A formatted released changelog section, or an empty string if there is
            no content to keep.
        """
        sections = []
        current_heading = None
        current_lines: list[str] = []

        for line in unreleased_body:
            if line.startswith("### "):
                if current_heading is not None:
                    body_text = "".join(current_lines).strip()
                    if body_text and not all(is_blank_item(l) for l in current_lines):
                        sections.append(current_heading + body_text + "\n")
                current_heading = line
                current_lines = []
            else:
                current_lines.append(line)

        if current_heading is not None:
            body_text = "".join(current_lines).strip()
            if body_text and not all(is_blank_item(l) for l in current_lines):
                sections.append(current_heading + body_text + "\n")

        if not sections:
            return ""

        return new_header + "\n\n" + "\n".join(sections)

    if not path.exists():
        path.write_text("# Changelog\n\n" + blank_unreleased + new_header + "\n", encoding="utf-8")
        return

    existing = path.read_text(encoding="utf-8")

    if "## Unreleased" not in existing:
        path.write_text(existing.rstrip() + "\n\n" + blank_unreleased + new_header + "\n", encoding="utf-8")
        return

    lines = existing.splitlines(keepends=True)
    unreleased_idx = next(i for i, line in enumerate(lines) if line.startswith("## Unreleased"))

    next_section_idx = len(lines)
    for i in range(unreleased_idx + 1, len(lines)):
        if lines[i].startswith("## ") and not lines[i].startswith("## Unreleased"):
            next_section_idx = i
            break

    unreleased_body = lines[unreleased_idx + 1:next_section_idx]
    released_section = build_released_section(unreleased_body)

    new_lines = []
    new_lines.extend(lines[:unreleased_idx])
    new_lines.append(blank_unreleased)
    if released_section:
        new_lines.append(released_section + "\n")
    new_lines.extend(lines[next_section_idx:])

    path.write_text("".join(new_lines), encoding="utf-8")


def main() -> None:
    """
    Parse command-line arguments and update version references and changelog.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="New version, e.g. 1.2.3 or 1.2.3a1")
    parser.add_argument(
        "--pyproject",
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml",
    )
    parser.add_argument(
        "--init",
        default=Path("src") / "mada_tools" / "__init__.py",
        help="Path to __init__.py",
    )
    parser.add_argument(
        "--changelog",
        default=Path("CHANGELOG.md"),
        help="Optional path to CHANGELOG.md",
    )
    args = parser.parse_args()

    pyproject = Path(args.pyproject)
    init_file = Path(args.init)
    changelog = Path(args.changelog)

    changed_pyproject = update_file(pyproject, VERSION_RE, args.version)
    changed_init = update_file(init_file, INIT_RE, args.version)

    if not changed_pyproject:
        print(f"Warning: did not find version in {pyproject}")
    if not changed_init:
        print(f"Warning: did not find __version__ in {init_file}")

    prepend_changelog_section(changelog, args.version)


if __name__ == "__main__":
    main()

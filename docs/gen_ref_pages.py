"""
Generate the code reference pages.

This module generates the API reference pages for the project.
It uses the `mkdocs_gen_files` package to create the necessary Markdown files
at build time.
"""

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

TOP_LEVEL_MODULE = Path("src/mada_tools")

API_REFERENCE = Path("developer_guide")

# If you want to ignore certain files or directories, add their patterns here.
IGNORE_PATTERNS = []


def should_ignore(path: Path) -> bool:
    """
    Check if the given path matches any ignore patterns.

    Args:
        path (Path): The path to check.

    Returns:
        bool: True if the path should be ignored, False otherwise.
    """
    for pattern in IGNORE_PATTERNS:
        pattern = str(pattern)
        if path.is_relative_to(Path(pattern)):
            return True
        if path.match(pattern):
            return True
    return False


for path in sorted(TOP_LEVEL_MODULE.rglob("*.py")):
    if should_ignore(path):
        continue
    module_path = path.relative_to(TOP_LEVEL_MODULE).with_suffix("")
    doc_path = path.relative_to(TOP_LEVEL_MODULE).with_suffix(".md")
    full_doc_path = API_REFERENCE / doc_path

    parts = list(module_path.parts)

    if parts[-1] == "__init__":  #
        parts = parts[:-1]
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")
        if len(parts) == 0:
            continue
    elif parts[-1] == "__main__":
        continue

    nav[parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        identifier = ".".join(parts)
        print("::: " + identifier, file=fd)

    mkdocs_gen_files.set_edit_path(full_doc_path, path)


# NOTE: SUMMARY.md has to be the name of the nav file
summary_file = API_REFERENCE / "SUMMARY.md"
with mkdocs_gen_files.open(summary_file, "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())

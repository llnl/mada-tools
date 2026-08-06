"""
Generate the code reference pages.

This module generates the API reference pages for the project.
It uses the `mkdocs_gen_files` package to create the necessary Markdown files
at build time.
"""

import importlib.util
from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

PACKAGE_NAME = "mada_tools"

package_spec = importlib.util.find_spec(PACKAGE_NAME)
if package_spec is None or package_spec.submodule_search_locations is None:
    raise RuntimeError(f"Unable to find installed package {PACKAGE_NAME!r}.")

TOP_LEVEL_MODULE = Path(next(iter(package_spec.submodule_search_locations))).resolve()

API_REFERENCE = Path("developer_guide")

# If you want to ignore certain files or directories, add their patterns here.
IGNORE_PATTERNS = [Path("_docs")]


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
    relative_path = path.relative_to(TOP_LEVEL_MODULE)
    if should_ignore(relative_path):
        continue
    module_path = relative_path.with_suffix("")
    doc_path = relative_path.with_suffix(".md")
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
        identifier = ".".join([PACKAGE_NAME, *parts])
        print("::: " + identifier, file=fd)

    mkdocs_gen_files.set_edit_path(full_doc_path, Path("src") / PACKAGE_NAME / relative_path)


# NOTE: SUMMARY.md has to be the name of the nav file
summary_file = API_REFERENCE / "SUMMARY.md"
with mkdocs_gen_files.open(summary_file, "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())

"""
Generate the code reference pages.

This script is executed by ``mkdocs-gen-files`` at docs build time.
"""

from pathlib import Path

from mada_tools.docs import ApiReferenceMapping, generate_api_reference_pages

generate_api_reference_pages(
    [
        ApiReferenceMapping(
            package_name="mada_tools",
            api_reference_path=Path("developer_guide"),
            ignore_patterns=(Path("_docs"),),
        )
    ]
)

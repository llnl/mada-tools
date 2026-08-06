# Documentation Deployment

This project uses [**Material for MkDocs**](https://squidfunk.github.io/mkdocs-material/) and [**mike**](https://github.com/jimporter/mike) to publish versioned documentation to **GitHub Pages**.

## Overview

Two GitHub Actions workflows publish the docs:

| Workflow | Trigger | Publishes |
|---|---|---|
| `publish-dev-docs.yml` | Push to `develop` | Development docs |
| `publish-docs.yml` | Published GitHub release | Stable release docs |

The published docs are stored in the `gh-pages` branch.

## Development docs

The `publish-dev-docs.yml` workflow runs whenever changes are pushed to `develop`.

It:

1. Checks out the repository
2. Fetches the existing `gh-pages` branch
3. Configures Git author information for the deployment commit
4. Installs the Python documentation dependencies
5. Runs:
    ```bash
    mike deploy --push develop
    ```
This publishes the current `develop` branch documentation as the `develop` version on GitHub Pages.

## Stable release docs

The `publish-docs.yml` workflow runs when a GitHub release is published.

It:

1. Checks out the repository
2. Fetches the existing `gh-pages` branch
3. Configures Git author information for the deployment commit
4. Reads the release tag from GitHub
5. Installs the Python documentation dependencies
6. Runs:
    ```bash
    mike deploy --push --update-aliases ${RELEASE_TAG_VERSION} latest
    mike set-default --push latest
    ```
This publishes the release documentation under the release version and updates the `latest` alias to point to that release.

## Version layout

The site typically contains:

| Version | Purpose |
|---|---|
| `develop` | Docs for ongoing development |
| `latest` | Docs for the most recent stable release |
| `x.y.z` | Docs for a specific release tag |

## Local documentation build

You can build the docs locally with:
```bash
pip install ".[docs]"
mkdocs build
```
If you want to test version publishing locally, use `mike` commands in a Git repository with the `gh-pages` branch available.

## Exporting packaged docs

MADA Tools wheels include the MkDocs source project so downstream packages can build compatible documentation without assuming a repository checkout. Export the packaged documentation with:

```bash
mada-tools export-docs mada-tools-docs
cd mada-tools-docs
mkdocs build --strict
```

The export contains `mkdocs.yaml`, the `docs/` source tree, and supporting fragments such as `configs/` files used by Markdown snippets. API reference generation imports `mada_tools` from the installed environment, so build the exported docs from an environment where the target wheel is installed.

The `src/mada_tools/_docs` package resource is generated during wheel and source distribution builds from the repository's top-level `docs/`, `configs/`, and `mkdocs.yaml` sources. Do not edit or check in a duplicate `_docs` tree.

## Notes

- The workflows require write access to the repository so they can update `gh-pages`.
- `fetch-depth: 0` is used so `mike` can work with full git history.
- The `gh-pages` branch is not edited manually, it is managed by the deployment workflows.

## Troubleshooting

If the docs do not appear as expected:

- confirm the workflow completed successfully
- check that `gh-pages` was updated
- verify the correct version folder was published
- confirm the GitHub Pages site is configured to use the `gh-pages` branch

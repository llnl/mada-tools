# Release Workflow

This project uses a branch-based release process designed to keep ongoing development separate from stable published releases.

## Branch roles

| Branch | Purpose |
|---|---|
| `develop` | Active development branch for ongoing work, feature integration, and pre-release preparation |
| `release/<version>` | Temporary release branch used to finalize a stable release |
| `main` | Stable branch containing only released, production-ready code |

## Bumping the Version

Bumping the version number can be done from the top of the repository with:

```bash
python bump_version.py <version number>
```

This script will:

1. Update the version in `src/mada_tools/__init__.py`
2. Update the version in `pyproject.toml`
3. Tag the "Unreleased" section of the `CHANGELOG.md` file with a version number and date, trim empty sections, and create a new, blank "Unreleased" section at the top of the file

## Stable releases

Stable releases are prepared from a dedicated release branch so that final release changes are isolated from ongoing development work.

1. Create a `release/<version>` branch from `develop`.
2. Use the release branch to [finalize the version number](#bumping-the-version), update the changelog, and apply any last release-specific fixes.
3. Merge `release/<version>` into `main`.
4. Create the stable GitHub release from `main`. During this process, you'll need to create a new tag (e.g., "v0.1.1") that's associated with this release.

The `release/<version>` branch can be retained for reference.

## Pre-releases

Pre-releases are created directly from `develop`.

1. [Update the version](#bumping-the-version) in `develop` to the next development version or pre-release version.
2. Create the GitHub pre-release from `develop`. During this process, you'll need to create a new tag (e.g., "v0.1.1b1") that's associated with this release.

This keeps pre-release work aligned with active development while avoiding disruption to the stable release process.

## Branch synchronization

In this workflow, `main` and `develop` are usually synchronized only at release boundaries. After a stable release, `main` contains the released version, while `develop` may continue forward with the next development or pre-release version.

If the stable release includes changes that are not already present in `develop`, merge `main` back into `develop` so the two branches remain consistent.

## Summary

| Release type | Branch path | Release source |
|---|---|---|
| Stable release | `develop` -> `release/<version>` -> `main` | `main` |
| Pre-release | `develop` | `develop` |

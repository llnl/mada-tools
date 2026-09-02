# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added
- Added shared plugin documentation staging helpers and the `mada-tools plugin-docs` command group for preparing, building, serving, and cleaning plugin-local combined docs sites
- Added shared API reference page generation helper for plugin documentation builds

### Changed
- Updated installation docs to describe package installation from PyPI and optional server discovery behavior

### Fixed
- Kept available MCP server discovery working when an optional server dependency is missing

## 0.2.0 - 2026-08-24

### Added
- Packaged the documentation source project in wheels and added `mada-tools export-docs` command
- Added wheel-based documentation package validation to CI
- Added common parameter_samples_generator and associated documentation.
- Support for Windows OS
- Support for Python 3.14
- Support for Hubcast
- GitLab CI for Hubcast
- Simulation tests and generic tools for LLM MCP Tool tests
- DOI link to README
- Public `mada_tools.testing` utilities for reusable server validation and agent-driven end-to-end tests in extension packages

### Changed
- Refactored the `JobMonitorServer` and `ProfessorServer` to utilize `BaseMCPServer.run_tool()`
- Dropped support for Python 3.10
- Updated how plugins are discovered and registered to extend capabilities past just MCP servers
- Converted MCP Tools to async so that long running tools do not block the chat.
- Promoted `MultiServerAgent` into package code under `mada_tools.agents` and refactored the interactive example to consume the supported library API

## 0.1.1 - 2026-06-23

### Added
- `bump_version.py` script to help with releases
- CHANGELOG to track changes across releases
- workflows for publishing develop and stable versions of documentation
- workflows for running CI

## 0.1.0 - 2026-06-17

Initial release. See full set of documentation for what this project contains.

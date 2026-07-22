# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added
- Added common parameter_samples_generator and associated documentation.
- Support for Windows OS
- Support for Python 3.14
- Support for Hubcast
- GitLab CI for Hubcast
- Simulation tests and generic tools for LLM MCP Tool tests
- DOI link to README

### Changed
- Refactored the `JobMonitorServer` and `ProfessorServer` to utilize `BaseMCPServer.run_tool()`
- Dropped support for Python 3.10
- Updated how plugins are discovered and registered to extend capabilities past just MCP servers
- Converted MCP Tools to async so that long running tools do not block the chat.

### Fixed
-

## 0.1.1 - 2026-06-23

### Added
- `bump_version.py` script to help with releases
- CHANGELOG to track changes across releases
- workflows for publishing develop and stable versions of documentation
- workflows for running CI

## 0.1.0 - 2026-06-17

Initial release. See full set of documentation for what this project contains.

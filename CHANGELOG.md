# Changelog

All notable project changes are documented in this file.

## 0.1.1 - 2026-11-20

### Added

- Added the project banner to the top of the README.
- Added the project ICO to the standalone Windows executable.
- Added a central application version and CLI `--version` output.
- Added external per-user GUI settings storage in `%APPDATA%\OPC_UA_TIA_Export\settings.json`, excluding passwords and insecure-connection acknowledgement.

### Changed

- Updated local and GitHub Actions PyInstaller builds to include `icon.ico`.

## 0.1.0 - 2026-11-19

### Added

- Initial OPC UA browser and TIA Portal HMI tag export.
- PySide6 desktop GUI and command-line interface.
- Generic, sanitized 40-column Siemens TIA HMI workbook.
- Live browse status, configurable output folder, and type mapping.
- GitHub Actions release workflow and SHA-256 checksums.

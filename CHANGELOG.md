# Changelog

All notable project changes are documented in this file.

## 0.2.1 - 2026-11-24

### Fixed

- Restored replacement of periods with underscores in generated TIA tag names.

### Added

- Added buttons to copy or open the folder containing the latest generated workbook.

## 0.2.0 - 2026-11-20

### Added

- Added the Source-Available Non-Commercial Redistribution License 1.0. It permits professional use and free redistribution of original or modified versions with license/source attribution, but prohibits charging for or monetizing the Software. It applies to versions v0.1.0 and v0.1.1.
- Added dedicated `assets/branding/` and `assets/screenshots/` directories for project imagery.
- Added a sanitized GUI screenshot to the README.
- Added GUI buttons to open the project README and create a prefilled GitHub issue with application version and Status log.

### Changed

- Fixed the Qt window/taskbar icon in packaged one-file builds by bundling and applying the ICO at runtime.
- Removed TIA workbook and example-tag inputs; the 40-column TIA HMI import format is now generated directly in code.
- Preserved periods inside NodeId components when generating TIA tag names, including names such as `1210.10-IP1`.
- Added explicit, fingerprint-based confirmation for discovered self-signed server certificates in the GUI.
- Kept entered passwords available for repeated exports during one application session without persisting them.
- Added automatic generation and reuse of the GUI's self-signed OPC UA client identity, so secure connections no longer require manually selected client certificate and key files.
- Added an explicit privacy warning before opening a prefilled GitHub issue so users can remove sensitive data from the submitted log.
- Added one bounded reconnect when a server invalidates a newly created OPC UA session with `BadSessionClosed` or `BadSessionIdInvalid`.

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

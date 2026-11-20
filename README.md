![OPC UA to TIA Portal HMI Tag Export](assets/branding/banner.png)

# OPC UA to TIA Portal HMI Tags

**GitHub description:** Browse OPC UA address spaces and export supported scalar variables to Siemens TIA Portal HMI tag workbooks.

Browse an OPC UA server's visible address space and export supported scalar variables to a Siemens TIA Portal HMI tag workbook. The project includes a Windows desktop GUI and a command-line interface.

The client browses metadata and reads only the attributes needed to classify variables. It does not write to the PLC or read process values. Server permissions and browse filters limit what can be discovered, so an export is not a guarantee of every variable in a controller.

## Features

- Browse from the standard `Objects` node or a supplied starting NodeId.
- Show live counts for visited nodes, variables, and eligible tags.
- Apply a limit to eligible tags, or use `0` to browse without a tag limit.
- Create a TIA HMI workbook from the bundled generic template or a user-selected workbook.
- Run either the graphical application or the CLI.
- Remember non-secret GUI settings between executable versions in a per-user external file.
- Keep passwords and security acknowledgements in memory only for the current run.

## Requirements

- Windows 10 or later for the supplied packaging script and release executable.
- Python 3.10 or later to run from source. Python 3.12 is used by the release workflow.
- An OPC UA server reachable from the computer running the application.
- The bundled generic TIA workbook for Siemens S7 OPC UA, or a TIA Portal HMI workbook with a connected OPC UA example tag using a string NodeId.
- For secure connections, client and server certificate files and the matching client private key.

Runtime dependencies are declared in `requirements.txt`: `asyncua`, `openpyxl`, and `PySide6`. Build-only dependencies, including PyInstaller, are in `requirements-build.txt`.

## Run From Source

Install the runtime dependencies and start the GUI:

```powershell
python -m pip install -r requirements.txt
python .\opc_ua_export_app.py
```

To use the CLI, inspect its options first:

```powershell
python .\opc_ua_export.py --help
```

## GUI

Fields marked with `*` are required for an export. The application starts with the bundled generic Siemens S7 OPC UA workbook and its `ExampleTag` row selected. For another server namespace or TIA configuration, choose a workbook exported from that TIA project and enter the exact OPC UA example tag name. Choose an output folder; each successful run creates a timestamped `.xlsx` file there.

The GUI stores its non-secret fields in `%APPDATA%\OPC_UA_TIA_Export\settings.json`. This external per-user file is not replaced when a new executable is installed. It records the endpoint, connection name, username, security selection and certificate paths, workbook/example selection, output folder, start node, limit, and timeout. It never records the password, private key contents, certificate contents, or the acknowledgement for unencrypted communication. Delete the JSON file to reset remembered settings.

The GUI supports these settings:

| Setting | Required or optional | Details |
| --- | --- | --- |
| OPC UA endpoint | Required | Must use `opc.tcp://`; credentials in the endpoint URL are rejected. |
| TIA HMI connection name | Required | Must already exist in the target TIA project. |
| Authentication | Required choice | Enter a username and password, or select anonymous access. |
| Channel security | Required choice | Select `Sign` or `SignAndEncrypt`, or explicitly acknowledge unencrypted communication. |
| Security policy and certificates | Required for secure mode | Uses `Basic256Sha256`; select the client certificate, matching private key, and verified server certificate. |
| TIA workbook | Required; generic workbook preselected | The bundled template targets the Siemens S7 OPC UA namespace. Select another workbook if your server uses a different namespace or project configuration. |
| Example tag name | Required; `ExampleTag` preselected | Identifies the workbook row whose settings are used as the export template. |
| Export folder | Required | Destination for the generated workbook. |
| Starting NodeId | Optional | Defaults to `Objects`. |
| Eligible tag limit | Optional | Defaults to `100`; `0` means no limit. |
| Request timeout | Optional | Defaults to 10 seconds. |

The status pane reports browse counts and errors while the browse runs. It also shows the output file path after a workbook is created.

![OPC UA to TIA HMI GUI](assets/screenshots/gui-main.png)

## Import in TIA Portal

1. In TIA Portal, open the target HMI and use the HMI tag table import function for Excel files.
2. Select the generated `tia_hmi_....xlsx` workbook.
3. Keep the `Hmi Tags` worksheet selection and map/import the rows with TIA's supported HMI tag settings.
4. Confirm that the tag names, `Connection`, `Address`, and data types match the intended PLC connection.

<!-- Add assets/screenshots/tia-hmi-tag-import.png to show the import workflow here. -->

### Find the HMI Connection Name

The exporter requires the existing HMI connection name exactly as it appears in TIA Portal. To find it, open the HMI project, inspect its device connections, and use the connection name assigned to the OPC UA endpoint. Do not use a PLC hardware name, HMI device name, or guessed placeholder; paste the exact value into the GUI or `--connection` option.

<!-- Add assets/screenshots/tia-hmi-connection.png to show where to find the connection name. -->

Before using the imported tags in production, perform a small offline import test and verify names, addresses, types, and live values in the target TIA version.

## CLI

Secure connection example:

```powershell
python .\opc_ua_export.py `
  --endpoint "opc.tcp://plc.example.local:4840" `
  --user "operator" `
  --security "Basic256Sha256,SignAndEncrypt,client.der,client_key.pem,server.der" `
  --connection "HMI_Connection" `
  --limit 200
```

The password is requested interactively. The CLI defaults to `generic_tia_hmi_template.xlsx` and its `ExampleTag` row beside the application. This template targets Siemens S7 OPC UA. Use `--tia-template` and `--tia-example-tag` for another namespace or TIA configuration. The server certificate must be obtained through a trusted channel and verified before use. Protect the client private key and do not commit certificates or keys to source control.

For a trusted, isolated test network where the server supports no secure endpoint, unencrypted access must be explicitly enabled:

```powershell
python .\opc_ua_export.py `
  --endpoint "opc.tcp://plc.example.local:4840" `
  --user "operator" `
  --allow-insecure `
  --connection "HMI_Connection"
```

Without `--connection`, the CLI prompts for the existing TIA connection name. Without `--user`, it prompts for a username unless `--anonymous` is selected. Use `--tia-template` and `--tia-example-tag` only to select a different workbook or example row. The endpoint may also be entered interactively.

| Option | Required or optional | Description |
| --- | --- | --- |
| `--endpoint` | Optional prompt | OPC UA endpoint using the `opc.tcp` scheme. |
| `--user` / `--anonymous` | Required choice | Username is prompted when `--user` is omitted; `--anonymous` selects anonymous access. |
| `--security` / `--allow-insecure` | Required choice | Use `Basic256Sha256` with `Sign` or `SignAndEncrypt`, or explicitly allow an unencrypted channel. |
| `--tia-template` | Optional | TIA workbook path; defaults to the bundled generic Siemens S7 template. |
| `--tia-example-tag` | Optional | Example tag name; defaults to `ExampleTag`. |
| `--connection` | Optional prompt | Existing TIA HMI connection name. |
| `--start-node` | Optional | Starting NodeId; defaults to `Objects`. |
| `--limit` | Optional | Maximum eligible tags; defaults to `100`, and `0` disables the limit. |
| `--timeout` | Optional | Per-request timeout in seconds; defaults to `10`. |

## TIA Export

The selected workbook is read but never modified. The exporter uses its `Hmi Tags` worksheet and the selected example row as a template. It replaces the tag name, connection, address, and mapped data type fields while preserving the other example-row settings. Any `Substitute Value Usage` data rows are removed from the generated workbook. The bundled generic template is derived from a TIA workbook that was successfully imported during testing; its tag name, connection, NodeId, and workbook metadata are sanitized. Its 40-column layout and example-row settings are preserved.

Only scalar, readable variables with string NodeIds, a namespace matching the example tag, and one of the supported built-in types are exported. Arrays, strings, custom types, unsupported types, and variables without confirmed read access are skipped. This is intentionally a limited HMI export, not a complete OPC UA type exporter.

| OPC UA type | TIA `DataType` | TIA `HMI DataType` | `Length` in bytes |
| --- | --- | --- | ---: |
| Boolean | Boolean | Bool | 1 |
| Int16 | Int16 | Int | 2 |
| UInt16 | UInt16 | UInt | 2 |
| Int32 | Int32 | DInt | 4 |
| UInt32 | UInt32 | UDInt | 4 |
| Float | Float | Real | 4 |
| Double | Double | LReal | 8 |

The output tag name is derived from the string NodeId identifier. Characters not accepted by TIA are replaced with underscores; the original NodeId address is preserved. If normalization creates duplicate names, the export stops rather than silently overwriting a tag.

## Security Notes

- Prefer `SignAndEncrypt` and verify the server certificate before selecting it.
- Unencrypted OPC UA may expose credentials and traffic to other systems on the network. The CLI requires `--allow-insecure`; the GUI requires an explicit acknowledgement.
- The GUI persists non-secret configuration under `%APPDATA%\OPC_UA_TIA_Export\settings.json`, including usernames, endpoint text, and local certificate paths. It never persists passwords, certificate/private-key contents, or the explicit unencrypted-communication acknowledgement. Treat the JSON file as user configuration and protect access to the Windows profile as appropriate.
- Browsing can create load on a controller. Start with a low eligible-tag limit and coordinate with the system owner before a full browse.
- Treat generated workbooks as potentially sensitive: they contain server addresses and tag identifiers. Store and share them according to the site's data-handling rules.
- Review any user-provided workbook before use. The application preserves selected template settings, so do not use an untrusted workbook.
- TIA connection names are copied into output but cannot be checked against the target TIA project by this application.
- This software is not a safety system and does not replace an engineering review or an offline TIA import test.

## Tests

Run the local tests with:

```powershell
python -m unittest -v test_opc_ua_export test_opc_ua_export_app test_tia_hmi_export
```

The OPC UA integration tests start a local test server. They do not connect to a production PLC.

## Build a Windows Executable

Install build dependencies and package the GUI:

```powershell
python -m pip install -r requirements-build.txt
.\build_exe.ps1
```

The result is `dist\OPC_UA_TIA_Export.exe` alongside `dist\generic_tia_hmi_template.xlsx`. The executable uses `assets\branding\icon.ico` as its Windows application icon. The standalone executable includes Python and the application dependencies; users do not need a separate Python installation. The generic workbook contains no PLC export data, certificates, or private keys. Each user supplies certificate files for secure connections.

The release workflow builds on a clean Windows GitHub-hosted runner with Python 3.12. To reproduce it locally, use Windows and the dependency versions in the requirements files. The first launch of a PyInstaller one-file application can take a few seconds while bundled files are extracted.

## GitHub Releases

Pushing a version tag matching `v*` runs `.github/workflows/release.yml`. The workflow runs the test suite, creates a clean Windows GUI executable, writes SHA-256 checksums, and publishes the executable, generic TIA workbook, and checksum file to a GitHub Release. It does not package certificates, keys, or PLC export data. The generic workbook targets Siemens S7 OPC UA; users with another namespace or project configuration can select their own TIA export. If a tag-triggered run fails and the workflow is corrected on `main`, retry it without moving the tag with `gh workflow run release.yml --ref main -f release_tag=v0.1.1`.

To create a release after reviewing and committing the source changes:

```powershell
git tag v0.1.1
git push origin v0.1.1
```

See `CHANGELOG.md` for the version history.

GitHub Actions requires `contents: write` permission for the workflow token. Release assets should be verified against the published `SHA256SUMS.txt` before use.

## Dependencies

- `asyncua`: OPC UA client and local test server.
- `openpyxl`: read and create TIA-compatible Excel workbooks.
- `PySide6`: desktop GUI.
- `PyInstaller` (build only): package the Windows executable.

## License

This project is **source-available**, not Open Source. The [Source-Available Non-Commercial Redistribution License 1.0](LICENSE.md) permits personal and professional use, plus free redistribution of original or modified versions when the license, attribution, and complete corresponding source code are included. It prohibits charging for, monetizing, bundling into paid offerings, or otherwise earning revenue from the Software or access to it. The user may sell their own products and services created with the Software when the Software itself is not the paid or distributed part of that offering.

The license applies to all published project versions, including `v0.1.0` and `v0.1.1`, their source, binaries, and release assets, unless a later release explicitly states different terms. Third-party packages remain governed by their own licenses.
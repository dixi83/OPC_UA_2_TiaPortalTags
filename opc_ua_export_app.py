from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import threading
import traceback
from pathlib import Path
from urllib.parse import urlencode

from asyncua.crypto import cert_gen
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID
from PySide6.QtCore import QProcess, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opc_ua_export import BASE_DIR, main as run_export
from settings_store import default_settings_path, load_settings, save_settings
from version import __version__

APPLICATION_URI = "urn:opc-ua-tia-export:client"
REPOSITORY_URL = "https://github.com/dixi83/OPC_UA_2_TiaPortalTags"


def github_issue_url(status_log: str) -> str:
    """Build a prefilled GitHub issue while preserving the full log in the form body."""
    truncated_log = status_log[-12000:]
    if len(status_log) > len(truncated_log):
        truncated_log = "[Earlier log content was omitted. Copy the full Status log if relevant.]\n\n" + truncated_log
    body = f"""## Environment

- Application version: `{__version__}`
- Windows version:
- TIA Portal version:
- HMI type (Unified Runtime PC / Unified Comfort Panel / other):

## Problem

Describe what happened and what you expected.

## Status log

```text
{truncated_log or "No status log was available."}
```

## Privacy check

Before submitting, personally review and remove endpoint addresses, hostnames, usernames, project names, certificate details, tag names, file paths, and any other sensitive information.

## TIA import failure

If the failure happens while importing the generated workbook into TIA Portal, attach the TIA Portal `import.xml` and identify the affected HMI and TIA version.
"""
    query = urlencode({"title": f"Bug report - OPC UA to TIA HMI {__version__}", "body": body})
    return f"{REPOSITORY_URL}/issues/new?{query}"


def application_icon() -> QIcon:
    """Load the bundled ICO in source and one-file PyInstaller environments."""
    resource_root = Path(getattr(sys, "_MEIPASS", BASE_DIR))
    return QIcon(str(resource_root / "assets" / "branding" / "icon.ico"))


def ensure_client_identity(directory: Path) -> tuple[Path, Path]:
    """Create or refresh the per-user OPC UA client certificate and key."""
    directory.mkdir(parents=True, exist_ok=True)
    certificate = directory / "client.der"
    private_key = directory / "client.pem"
    asyncio.run(
        cert_gen.setup_self_signed_certificate(
            private_key,
            certificate,
            APPLICATION_URI,
            socket.gethostname(),
            [ExtendedKeyUsageOID.CLIENT_AUTH],
            {"organizationName": "OPC UA to TIA Export"},
        )
    )
    return certificate, private_key


class ExportWorker(QThread):
    """Run the asynchronous export on a worker thread and emit UI-safe signals."""

    progress_message = Signal(str)
    completed = Signal(int)
    failed = Signal(str)
    certificate_confirmation_requested = Signal(str, str)

    def __init__(self, args, password, output_dir, accepted_server_certificates=None):
        super().__init__()
        self.args = args
        self.password = password
        self.output_dir = output_dir
        self.accepted_server_certificates = accepted_server_certificates if accepted_server_certificates is not None else set()
        self._certificate_decisions = {}

    def run(self):
        """Execute one export and forward progress and terminal status through Qt signals."""
        try:
            result = asyncio.run(
                run_export(
                    self.args,
                    password=self.password,
                    progress=self.progress_message.emit,
                    output_dir=self.output_dir,
                    certificate_validator=self._validate_server_certificate,
                )
            )
            self.completed.emit(result)
        except Exception as exc:
            message = str(exc).strip() or repr(exc)
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self.failed.emit(f"{type(exc).__name__}: {message}\n{details}")
        finally:
            # Drop this worker's reference to the password as soon as the run ends.
            self.password = None

    async def _validate_server_certificate(self, certificate, application):
        fingerprint = certificate.fingerprint(hashes.SHA256()).hex(":")
        if fingerprint in self.accepted_server_certificates:
            return
        ready = threading.Event()
        decision = [False]
        self._certificate_decisions[fingerprint] = (ready, decision)
        name = getattr(getattr(application, "ApplicationName", None), "Text", "")
        application_uri = getattr(application, "ApplicationUri", "")
        details = (
            "Trust this OPC UA server certificate for the rest of this application session?\n\n"
            f"Application: {name or '<not provided>'}\n"
            f"Application URI: {application_uri or '<not provided>'}\n"
            f"Subject: {certificate.subject.rfc4514_string()}\n"
            f"Issuer: {certificate.issuer.rfc4514_string()}\n"
            f"Valid from: {certificate.not_valid_before_utc.isoformat()}\n"
            f"Valid until: {certificate.not_valid_after_utc.isoformat()}\n"
            f"SHA-256: {fingerprint}\n\n"
            "Accept only after verifying the fingerprint through a trusted channel."
        )
        self.certificate_confirmation_requested.emit(fingerprint, details)
        await asyncio.to_thread(ready.wait)
        if not decision[0]:
            raise ValueError("The server certificate was not accepted.")
        self.accepted_server_certificates.add(fingerprint)

    def set_certificate_decision(self, fingerprint, accepted):
        pending = self._certificate_decisions.pop(fingerprint, None)
        if pending is None:
            return
        ready, decision = pending
        decision[0] = accepted
        ready.set()


class ExportWindow(QMainWindow):
    """Collect validated export settings and show live OPC UA browse progress."""

    def __init__(self, settings_file: Path | None = None):
        super().__init__()
        self.setWindowTitle(f"OPC UA to TIA HMI {__version__}")
        self.resize(930, 900)
        self.setMinimumSize(780, 760)
        self.worker = None
        self.latest_export_path = None
        self.accepted_server_certificates = set()
        self.settings_file = Path(settings_file) if settings_file is not None else default_settings_path()

        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText("opc.tcp://host:4840")
        self.connection = QLineEdit()
        self.connection.setPlaceholderText("Existing name from TIA Portal")
        self.anonymous = QCheckBox("Anonymous access")
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.security_mode = QComboBox()
        self.security_mode.addItems(["Unencrypted", "Sign", "SignAndEncrypt"])
        self.security_ack = QCheckBox("I understand that credentials may be exposed on the network")
        self.policy = QComboBox()
        self.policy.setEditable(False)
        self.policy.addItems(["Basic256Sha256"])
        self.client_cert = QLineEdit()
        self.client_key = QLineEdit()
        self.server_cert = QLineEdit()
        self.output_dir = QLineEdit(str(BASE_DIR / "export"))
        self.start_node = QLineEdit()
        self.limit = QSpinBox()
        self.limit.setRange(0, 10000000)
        self.limit.setValue(100)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0.1, 3600)
        self.timeout.setDecimals(1)
        self.timeout.setValue(10)
        self.status = QLabel("Ready")
        self.status.setObjectName("status")
        self.activity = QProgressBar()
        self.activity.setRange(0, 1)
        self.activity.setTextVisible(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Progress and messages will appear here.")
        self.start_button = QPushButton("Start export")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start_export)
        self.readme_button = QPushButton("Open README")
        self.readme_button.clicked.connect(self._open_readme)
        self.issue_button = QPushButton("Report issue on GitHub")
        self.issue_button.clicked.connect(self._open_issue)
        self.copy_export_path_button = QPushButton("Copy latest export folder")
        self.copy_export_path_button.setEnabled(False)
        self.copy_export_path_button.clicked.connect(self._copy_latest_export_folder)
        self.open_export_folder_button = QPushButton("Open latest export folder")
        self.open_export_folder_button.setEnabled(False)
        self.open_export_folder_button.clicked.connect(self._open_latest_export_folder)

        self._restore_settings()
        self._build_layout()
        self.anonymous.toggled.connect(self._update_auth_state)
        self.security_mode.currentTextChanged.connect(self._update_security_state)
        self._update_auth_state()
        self._update_security_state()

    def _build_layout(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)
        title = QLabel("OPC UA to TIA HMI")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        settings_path_label = QLabel(f"Settings file: {self.settings_file}")
        settings_path_label.setObjectName("settingsPath")
        settings_path_label.setWordWrap(True)
        outer.addWidget(settings_path_label)
        outer.addWidget(QLabel("* required  |  Other fields are optional; populated values are defaults."))

        connection_group = QGroupBox("Connection")
        connection_form = QFormLayout(connection_group)
        connection_form.addRow("OPC UA endpoint *", self.endpoint)
        connection_form.addRow("TIA HMI connection *", self.connection)
        connection_form.addRow("", self.anonymous)
        connection_form.addRow("Username (unless anonymous)", self.username)
        connection_form.addRow("Password (unless anonymous)", self.password)
        connection_form.addRow("Channel security *", self.security_mode)
        connection_form.addRow("", self.security_ack)
        connection_form.addRow("Security policy (secure mode)", self.policy)
        connection_form.addRow(
            "Client certificate (optional; generated automatically)",
            self._file_field(self.client_cert, "Browse...", "cert"),
        )
        connection_form.addRow(
            "Private key (optional; generated automatically)",
            self._file_field(self.client_key, "Browse...", "key"),
        )
        connection_form.addRow(
            "Server certificate (secure mode; optional after confirmation)",
            self._file_field(self.server_cert, "Browse...", "cert"),
        )
        outer.addWidget(connection_group)

        export_group = QGroupBox("Export settings")
        export_form = QFormLayout(export_group)
        export_form.addRow("Export folder *", self._directory_field(self.output_dir))
        self.start_node.setPlaceholderText("Optional; blank = Objects")
        export_form.addRow("Starting NodeId (optional)", self.start_node)
        limits = QWidget()
        limits_layout = QHBoxLayout(limits)
        limits_layout.setContentsMargins(0, 0, 0, 0)
        limits_layout.addWidget(QLabel("Suitable tag limit"))
        limits_layout.addWidget(self.limit)
        limits_layout.addWidget(QLabel("optional; default 100, 0 = unlimited"))
        limits_layout.addSpacing(18)
        limits_layout.addWidget(QLabel("Timeout (s)"))
        limits_layout.addWidget(self.timeout)
        limits_layout.addWidget(QLabel("optional; default 10 s"))
        limits_layout.addStretch(1)
        export_form.addRow("", limits)
        outer.addWidget(export_group)

        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        status_line = QHBoxLayout()
        status_line.addWidget(self.status, 1)
        status_line.addWidget(self.activity)
        status_layout.addLayout(status_line)
        export_actions = QHBoxLayout()
        export_actions.addWidget(self.copy_export_path_button)
        export_actions.addWidget(self.open_export_folder_button)
        export_actions.addStretch(1)
        status_layout.addLayout(export_actions)
        status_layout.addWidget(self.log, 1)
        outer.addWidget(status_group, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.readme_button)
        actions.addWidget(self.issue_button)
        actions.addStretch(1)
        actions.addWidget(self.start_button)
        outer.addLayout(actions)
        self.setCentralWidget(central)
        self.setStyleSheet(
            "QMainWindow { background: #f3f5f2; }"
            "QGroupBox { background: #ffffff; border: 1px solid #cbd4ce; border-radius: 5px;"
            " margin-top: 8px; padding-top: 8px; font-weight: 600; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
            "QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: white;"
            " border: 1px solid #aebbb3; border-radius: 3px; padding: 5px; }"
            "QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #147d69; }"
            "QLabel#pageTitle { color: #173d35; font-size: 20px; font-weight: 700; }"
            "QLabel#settingsPath { color: #5d6b64; font-size: 10px; }"
            "QLabel#status { color: #173d35; font-weight: 600; }"
            "QPushButton { padding: 7px 12px; }"
            "QPushButton#primaryButton { color: white; background: #147d69; border: 0; border-radius: 3px;"
            " font-weight: 600; min-width: 120px; }"
            "QPushButton#primaryButton:hover { background: #0e6857; }"
            "QPushButton#primaryButton:disabled { background: #8ca9a0; }"
        )

    def _file_field(self, line_edit, button_text, file_kind):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit, 1)
        button = QPushButton(button_text)
        button.clicked.connect(lambda: self._choose_file(line_edit, file_kind))
        layout.addWidget(button)
        return container

    def _directory_field(self, line_edit):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit, 1)
        button = QPushButton("Browse...")
        button.clicked.connect(self._choose_directory)
        layout.addWidget(button)
        return container

    def _choose_file(self, line_edit, file_kind):
        if file_kind == "key":
            file_filter = "Private key (*.pem *.key);;All files (*.*)"
        else:
            file_filter = "Certificate (*.der *.pem *.crt *.cer);;All files (*.*)"
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", line_edit.text(), file_filter)
        if path:
            line_edit.setText(path)

    def _choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Choose export folder", self.output_dir.text())
        if path:
            self.output_dir.setText(path)

    def _restore_settings(self):
        """Populate GUI fields from the per-user settings whitelist."""
        settings = load_settings(self.settings_file)
        text_fields = {
            "endpoint": self.endpoint,
            "connection": self.connection,
            "username": self.username,
            "client_cert": self.client_cert,
            "client_key": self.client_key,
            "server_cert": self.server_cert,
            "output_dir": self.output_dir,
            "start_node": self.start_node,
        }
        for key, field in text_fields.items():
            if key in settings:
                field.setText(settings[key])
        if "anonymous" in settings:
            self.anonymous.setChecked(settings["anonymous"])
        if settings.get("security_mode") in {"Unencrypted", "Sign", "SignAndEncrypt"}:
            self.security_mode.setCurrentText(settings["security_mode"])
        if settings.get("policy") == "Basic256Sha256":
            self.policy.setCurrentText(settings["policy"])
        if "limit" in settings:
            self.limit.setValue(min(settings["limit"], self.limit.maximum()))
        if "timeout" in settings:
            self.timeout.setValue(min(max(settings["timeout"], self.timeout.minimum()), self.timeout.maximum()))

    def _settings_data(self):
        """Return the supported non-secret values that may be written to disk."""
        return {
            "endpoint": self.endpoint.text().strip(),
            "connection": self.connection.text().strip(),
            "anonymous": self.anonymous.isChecked(),
            "username": self.username.text().strip(),
            "security_mode": self.security_mode.currentText(),
            "policy": self.policy.currentText(),
            "client_cert": self.client_cert.text().strip(),
            "client_key": self.client_key.text().strip(),
            "server_cert": self.server_cert.text().strip(),
            "output_dir": self.output_dir.text().strip(),
            "start_node": self.start_node.text().strip(),
            "limit": self.limit.value(),
            "timeout": self.timeout.value(),
        }

    def _save_settings(self):
        """Persist current non-secret fields without interrupting an export."""
        try:
            save_settings(self._settings_data(), self.settings_file)
        except OSError as exc:
            self.log.appendPlainText(f"Could not save settings: {exc}")

    def _update_auth_state(self, anonymous=None):
        is_anonymous = self.anonymous.isChecked() if anonymous is None else anonymous
        self.username.setEnabled(not is_anonymous)
        self.password.setEnabled(not is_anonymous)

    def _update_security_state(self, mode=None):
        selected_mode = self.security_mode.currentText() if mode is None else mode
        insecure = selected_mode == "Unencrypted"
        self.security_ack.setVisible(insecure)
        self.policy.setEnabled(not insecure)
        for field in (self.client_cert, self.client_key, self.server_cert):
            field.setEnabled(not insecure)
            parent = field.parentWidget()
            if parent:
                for button in parent.findChildren(QPushButton):
                    button.setEnabled(not insecure)

    def _arguments(self):
        endpoint = self.endpoint.text().strip()
        connection = self.connection.text().strip()
        output_text = self.output_dir.text().strip()
        if not endpoint:
            raise ValueError("Enter the OPC UA endpoint.")
        if not connection or connection.casefold() in {"<internal tag>", "<no value>", "todo_connection"}:
            raise ValueError("Enter an existing TIA HMI connection name.")
        if not output_text:
            raise ValueError("Choose an export folder.")
        output_dir = Path(output_text)

        anonymous = self.anonymous.isChecked()
        username = self.username.text().strip()
        password = self.password.text()
        if not anonymous and (not username or not password):
            raise ValueError("Enter a username and password, or select anonymous access.")

        security_mode = self.security_mode.currentText()
        security = None
        allow_insecure = False
        application_uri = None
        if security_mode == "Unencrypted":
            if not self.security_ack.isChecked():
                raise ValueError("Explicitly confirm that you allow unencrypted communication.")
            allow_insecure = True
        else:
            client_certificate = self.client_cert.text().strip()
            client_key = self.client_key.text().strip()
            if bool(client_certificate) != bool(client_key):
                raise ValueError("Select both the client certificate and private key, or leave both empty.")
            if client_certificate and client_key:
                if not all(Path(path).is_file() for path in (client_certificate, client_key)):
                    raise ValueError("The selected client certificate or private key file does not exist.")
                client_values = [client_certificate, client_key]
            else:
                generated = ensure_client_identity(self.settings_file.parent / "client-identity")
                client_values = [str(path) for path in generated]
                application_uri = APPLICATION_URI
            server_certificate = self.server_cert.text().strip()
            if server_certificate and not Path(server_certificate).is_file():
                raise ValueError("The selected server certificate file does not exist.")
            security_values = [self.policy.currentText().strip(), security_mode, *client_values]
            if server_certificate:
                security_values.append(server_certificate)
            security = ",".join(security_values)

        args = argparse.Namespace(
            endpoint=endpoint,
            user=username or None,
            anonymous=anonymous,
            security=security,
            allow_insecure=allow_insecure,
            start_node=self.start_node.text().strip() or None,
            limit=self.limit.value(),
            connection=connection,
            timeout=self.timeout.value(),
            application_uri=application_uri,
        )
        return args, password, output_dir

    def _start_export(self):
        try:
            args, password, output_dir = self._arguments()
        except ValueError as exc:
            QMessageBox.warning(self, "Check input", str(exc))
            return
        self._save_settings()
        self.start_button.setEnabled(False)
        self.latest_export_path = None
        self.copy_export_path_button.setEnabled(False)
        self.open_export_folder_button.setEnabled(False)
        self.activity.setRange(0, 0)
        self.status.setText("Connecting to OPC UA server...")
        self.log.appendPlainText("Export started")
        self.worker = ExportWorker(args, password, output_dir, self.accepted_server_certificates)
        self.worker.progress_message.connect(self._show_progress)
        self.worker.completed.connect(self._export_completed)
        self.worker.failed.connect(self._export_failed)
        self.worker.certificate_confirmation_requested.connect(self._confirm_server_certificate)
        self.worker.start()

    def _confirm_server_certificate(self, fingerprint, details):
        answer = QMessageBox.question(
            self,
            "Trust server certificate?",
            details,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        accepted = answer == QMessageBox.StandardButton.Yes
        if accepted:
            self.accepted_server_certificates.add(fingerprint)
        if self.worker:
            self.worker.set_certificate_decision(fingerprint, accepted)

    def _show_progress(self, message):
        self.log.appendPlainText(message)
        if message.startswith(("Browsed:", "Found:")):
            self.status.setText(message)
        prefix = "TIA import workbook: "
        if message.startswith(prefix):
            self.latest_export_path = Path(message[len(prefix):].strip()).resolve()

    def _open_readme(self):
        QDesktopServices.openUrl(QUrl(f"{REPOSITORY_URL}/blob/main/README.md"))

    def _open_issue(self):
        answer = QMessageBox.warning(
            self,
            "Review issue contents",
            "The GitHub form will contain the current Status log and application version. "
            "Review and remove sensitive endpoints, users, paths, certificates, tag names, "
            "or project information before submitting anything. Continue to GitHub?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        issue_url = github_issue_url(self.log.toPlainText())
        QApplication.clipboard().setText(issue_url)
        QDesktopServices.openUrl(QUrl(issue_url))

    def _copy_latest_export_folder(self):
        if self.latest_export_path is None:
            return
        QApplication.clipboard().setText(str(self.latest_export_path.parent))
        self.status.setText("Latest export folder copied to clipboard")

    def _open_latest_export_folder(self):
        if self.latest_export_path is None:
            return
        if not QProcess.startDetached("explorer.exe", ["/select,", str(self.latest_export_path)]):
            QMessageBox.warning(self, "Could not open File Explorer", "Windows File Explorer could not be started.")

    def _export_completed(self, exit_code):
        self.activity.setRange(0, 1)
        self.activity.setValue(0)
        self.start_button.setEnabled(True)
        export_available = self.latest_export_path is not None and self.latest_export_path.is_file()
        self.copy_export_path_button.setEnabled(export_available)
        self.open_export_folder_button.setEnabled(export_available)
        self.status.setText("Export complete" if exit_code == 0 else f"Export complete with warnings (exit code {exit_code})")

    def _export_failed(self, error):
        self.activity.setRange(0, 1)
        self.activity.setValue(0)
        self.start_button.setEnabled(True)
        self.copy_export_path_button.setEnabled(False)
        self.open_export_folder_button.setEnabled(False)
        self.status.setText("Export stopped due to an error")
        self.log.appendPlainText("Error:\n" + error.rstrip())
        QMessageBox.critical(self, "Export failed", error.splitlines()[0] if error else "Unknown export error")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Export in progress", "Close this window after the export completes.")
            event.ignore()
            return
        self._save_settings()
        event.accept()


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setWindowIcon(application_icon())
    window = ExportWindow()
    window.setWindowIcon(application_icon())
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
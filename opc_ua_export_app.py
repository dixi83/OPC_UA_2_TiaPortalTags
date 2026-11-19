from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from PySide6.QtCore import QThread, Signal
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

from opc_ua_export import BASE_DIR, DEFAULT_TEMPLATE, main as run_export


class ExportWorker(QThread):
    """Run the asynchronous export on a worker thread and emit UI-safe signals."""

    progress_message = Signal(str)
    completed = Signal(int)
    failed = Signal(str)

    def __init__(self, args, password, output_dir):
        super().__init__()
        self.args = args
        self.password = password
        self.output_dir = output_dir
        """Run the asynchronous OPC UA export without blocking the Qt event loop."""

    def run(self):
        """Execute one export and forward progress and terminal status through Qt signals."""
        try:
            result = asyncio.run(
                run_export(
                    self.args,
                    password=self.password,
                    progress=self.progress_message.emit,
                    output_dir=self.output_dir,
                )
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            # Drop this worker's reference to the password as soon as the run ends.
            self.password = None


class ExportWindow(QMainWindow):
    """Collect validated export settings and show live OPC UA browse progress."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OPC UA to TIA HMI")
        self.resize(930, 900)
        self.setMinimumSize(780, 760)
        self.worker = None

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
        self.template = QLineEdit(str(DEFAULT_TEMPLATE))
        self.example_tag = QLineEdit("ExampleTag")
        self.example_tag.setPlaceholderText("Name of the example tag in the workbook")
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
        connection_form.addRow("Client certificate (secure mode)", self._file_field(self.client_cert, "Browse...", "cert"))
        connection_form.addRow("Private key (secure mode)", self._file_field(self.client_key, "Browse...", "key"))
        connection_form.addRow("Server certificate (secure mode)", self._file_field(self.server_cert, "Browse...", "cert"))
        outer.addWidget(connection_group)

        export_group = QGroupBox("Export settings")
        export_form = QFormLayout(export_group)
        export_form.addRow("TIA workbook *", self._file_field(self.template, "Browse...", "xlsx"))
        export_form.addRow("Example tag name *", self.example_tag)
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
        status_layout.addWidget(self.log, 1)
        outer.addWidget(status_group, 1)
        actions = QHBoxLayout()
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
        if file_kind == "xlsx":
            file_filter = "Excel workbook (*.xlsx);;All files (*.*)"
        elif file_kind == "key":
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
        template = Path(self.template.text().strip())
        output_text = self.output_dir.text().strip()
        if not endpoint:
            raise ValueError("Enter the OPC UA endpoint.")
        if not connection or connection.casefold() in {"<internal tag>", "<no value>", "todo_connection"}:
            raise ValueError("Enter an existing TIA HMI connection name.")
        if not template.is_file():
            raise ValueError(f"TIA workbook not found: {template}")
        if not output_text:
            raise ValueError("Choose an export folder.")
        output_dir = Path(output_text)
        example_tag = self.example_tag.text().strip()
        if not example_tag:
            raise ValueError("Enter the example tag name from the selected workbook.")

        anonymous = self.anonymous.isChecked()
        username = self.username.text().strip()
        password = self.password.text()
        if not anonymous and (not username or not password):
            raise ValueError("Enter a username and password, or select anonymous access.")

        security_mode = self.security_mode.currentText()
        security = None
        allow_insecure = False
        if security_mode == "Unencrypted":
            if not self.security_ack.isChecked():
                raise ValueError("Explicitly confirm that you allow unencrypted communication.")
            allow_insecure = True
        else:
            cert_values = [self.client_cert.text().strip(), self.client_key.text().strip(), self.server_cert.text().strip()]
            if not all(Path(path).is_file() for path in cert_values):
                raise ValueError("Select existing client certificate, private key, and server certificate files.")
            security = ",".join([self.policy.currentText().strip(), security_mode, *cert_values])

        args = argparse.Namespace(
            endpoint=endpoint,
            user=username or None,
            anonymous=anonymous,
            security=security,
            allow_insecure=allow_insecure,
            start_node=self.start_node.text().strip() or None,
            limit=self.limit.value(),
            tia_template=template,
            tia_example_tag=example_tag,
            connection=connection,
            timeout=self.timeout.value(),
        )
        return args, password, output_dir

    def _start_export(self):
        try:
            args, password, output_dir = self._arguments()
        except ValueError as exc:
            QMessageBox.warning(self, "Check input", str(exc))
            return
        self.start_button.setEnabled(False)
        self.activity.setRange(0, 0)
        self.status.setText("Connecting to OPC UA server...")
        self.log.appendPlainText("Export started")
        self.worker = ExportWorker(args, password, output_dir)
        self.worker.progress_message.connect(self._show_progress)
        self.worker.completed.connect(self._export_completed)
        self.worker.failed.connect(self._export_failed)
        self.worker.start()
        # Clear the visible input after the worker receives its in-memory copy.
        self.password.clear()

    def _show_progress(self, message):
        self.log.appendPlainText(message)
        if message.startswith(("Browsed:", "Found:")):
            self.status.setText(message)

    def _export_completed(self, exit_code):
        self.activity.setRange(0, 1)
        self.activity.setValue(0)
        self.start_button.setEnabled(True)
        self.status.setText("Export complete" if exit_code == 0 else f"Export complete with warnings (exit code {exit_code})")

    def _export_failed(self, error):
        self.activity.setRange(0, 1)
        self.activity.setValue(0)
        self.start_button.setEnabled(True)
        self.status.setText("Export stopped due to an error")
        self.log.appendPlainText("Error: " + error)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Export in progress", "Close this window after the export completes.")
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    window = ExportWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
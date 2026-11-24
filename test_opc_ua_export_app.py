import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from opc_ua_export import BASE_DIR, TIA_HEADERS, TIA_SUBSTITUTE_HEADERS
from opc_ua_export_app import (
    APPLICATION_URI,
    REPOSITORY_URL,
    ExportWindow,
    ExportWorker,
    application_icon,
    ensure_client_identity,
    github_issue_url,
)
from version import __version__


class ExportWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_requires_acknowledgement_for_unencrypted_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            window = ExportWindow(Path(directory) / "settings.json")
            self.addCleanup(window.close)
            window.endpoint.setText("opc.tcp://localhost:4840")
            window.connection.setText("test_connection")
            window.anonymous.setChecked(True)
            window.security_mode.setCurrentText("Unencrypted")

            with self.assertRaisesRegex(ValueError, "Explicitly confirm"):
                window._arguments()

            window.security_ack.setChecked(True)
            args, password, output_directory = window._arguments()
            self.assertTrue(args.allow_insecure)
            self.assertTrue(args.anonymous)
            self.assertEqual(args.limit, 100)
            self.assertEqual(args.timeout, 10)
            self.assertEqual(password, "")
            self.assertEqual(output_directory.name, "export")

    def test_settings_round_trip_excludes_secrets_and_unsafe_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            window = ExportWindow(settings_file)
            window.endpoint.setText("opc.tcp://localhost:4840")
            window.connection.setText("remembered_connection")
            window.username.setText("remembered_user")
            window.password.setText("must_not_be_saved")
            window.security_mode.setCurrentText("Unencrypted")
            window.security_ack.setChecked(True)
            window.start_node.setText("ns=2;s=Machine")
            window.limit.setValue(321)
            window.timeout.setValue(18.5)
            window.output_dir.setText(str(Path(directory) / "output"))
            window._save_settings()

            raw_settings = settings_file.read_text(encoding="utf-8")
            self.assertNotIn("must_not_be_saved", raw_settings)
            self.assertNotIn("password", raw_settings)
            self.assertNotIn("allow_insecure", raw_settings)
            window.close()

            restored = ExportWindow(settings_file)
            self.addCleanup(restored.close)
            self.assertEqual(restored.endpoint.text(), "opc.tcp://localhost:4840")
            self.assertEqual(restored.connection.text(), "remembered_connection")
            self.assertEqual(restored.username.text(), "remembered_user")
            self.assertEqual(restored.start_node.text(), "ns=2;s=Machine")
            self.assertEqual(restored.limit.value(), 321)
            self.assertEqual(restored.timeout.value(), 18.5)
            self.assertEqual(restored.password.text(), "")
            self.assertFalse(restored.security_ack.isChecked())

    def test_corrupt_settings_file_does_not_break_gui_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            settings_file.write_text("{not valid json", encoding="utf-8")
            window = ExportWindow(settings_file)
            self.addCleanup(window.close)
            self.assertEqual(window.limit.value(), 100)
            self.assertEqual(window.timeout.value(), 10)
            self.assertFalse(hasattr(window, "template"))
            self.assertFalse(hasattr(window, "example_tag"))

    def test_password_stays_available_for_later_exports_but_is_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            window = ExportWindow(settings_file)
            self.addCleanup(window.close)
            window.endpoint.setText("opc.tcp://localhost:4840")
            window.connection.setText("test_connection")
            window.username.setText("operator")
            window.password.setText("session-only-password")
            window.security_mode.setCurrentText("Unencrypted")
            window.security_ack.setChecked(True)
            worker = MagicMock()
            worker.isRunning.return_value = False

            with patch("opc_ua_export_app.ExportWorker", return_value=worker):
                window._start_export()

            self.assertEqual(window.password.text(), "session-only-password")
            self.assertNotIn("session-only-password", settings_file.read_text(encoding="utf-8"))
            worker.start.assert_called_once_with()

    def test_secure_server_certificate_can_be_confirmed_instead_of_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client_certificate = root / "client.der"
            client_key = root / "client.pem"
            client_certificate.write_bytes(b"certificate")
            client_key.write_bytes(b"key")
            window = ExportWindow(root / "settings.json")
            self.addCleanup(window.close)
            window.endpoint.setText("opc.tcp://localhost:4840")
            window.connection.setText("test_connection")
            window.anonymous.setChecked(True)
            window.security_mode.setCurrentText("SignAndEncrypt")
            window.client_cert.setText(str(client_certificate))
            window.client_key.setText(str(client_key))
            window.server_cert.clear()

            args, _, _ = window._arguments()

            self.assertEqual(args.security.count(","), 3)
            self.assertTrue(args.security.endswith(str(client_key)))

    def test_secure_mode_generates_and_reuses_client_identity_when_fields_are_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity_dir = root / "identity"
            generated_certificate, generated_key = ensure_client_identity(identity_dir)
            second_certificate, second_key = ensure_client_identity(identity_dir)

            self.assertEqual((generated_certificate, generated_key), (second_certificate, second_key))
            self.assertTrue(generated_certificate.is_file())
            self.assertTrue(generated_key.is_file())
            certificate_content = generated_certificate.read_bytes()
            key_content = generated_key.read_bytes()
            ensure_client_identity(identity_dir)
            self.assertEqual(generated_certificate.read_bytes(), certificate_content)
            self.assertEqual(generated_key.read_bytes(), key_content)

            window = ExportWindow(root / "settings.json")
            self.addCleanup(window.close)
            window.endpoint.setText("opc.tcp://localhost:4840")
            window.connection.setText("test_connection")
            window.anonymous.setChecked(True)
            window.security_mode.setCurrentText("SignAndEncrypt")

            args, _, _ = window._arguments()

            self.assertEqual(args.application_uri, APPLICATION_URI)
            self.assertTrue(args.security.endswith("client.pem"))
            self.assertIn("client-identity", args.security)

    def test_partial_manual_client_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            certificate = root / "client.der"
            certificate.write_bytes(b"certificate")
            window = ExportWindow(root / "settings.json")
            self.addCleanup(window.close)
            window.endpoint.setText("opc.tcp://localhost:4840")
            window.connection.setText("test_connection")
            window.anonymous.setChecked(True)
            window.security_mode.setCurrentText("SignAndEncrypt")
            window.client_cert.setText(str(certificate))

            with self.assertRaisesRegex(ValueError, "both the client certificate and private key"):
                window._arguments()

    def test_server_certificate_acceptance_is_reused_for_worker_session(self):
        certificate = MagicMock()
        certificate.fingerprint.return_value = b"\xaa\xbb"
        certificate.subject.rfc4514_string.return_value = "CN=test-server"
        certificate.issuer.rfc4514_string.return_value = "CN=test-ca"
        certificate.not_valid_before_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
        certificate.not_valid_after_utc = datetime(2027, 1, 1, tzinfo=timezone.utc)
        application = SimpleNamespace(
            ApplicationName=SimpleNamespace(Text="Test Server"),
            ApplicationUri="urn:test:server",
        )
        worker = ExportWorker(SimpleNamespace(), "", Path("."))
        prompts = []
        worker.certificate_confirmation_requested.connect(
            lambda fingerprint, details: (
                prompts.append((fingerprint, details)),
                worker.set_certificate_decision(fingerprint, True),
            )
        )

        asyncio.run(worker._validate_server_certificate(certificate, application))
        asyncio.run(worker._validate_server_certificate(certificate, application))

        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][0], "aa:bb")
        self.assertIn("SHA-256: aa:bb", prompts[0][1])
        self.assertIn("CN=test-server", prompts[0][1])

    def test_application_icon_resolves_from_assets(self):
        self.assertTrue((BASE_DIR / "assets" / "branding" / "icon.ico").is_file())
        self.assertFalse(application_icon().isNull())

    def test_issue_url_includes_version_log_and_privacy_warning(self):
        url = github_issue_url("sample error: timeout")

        self.assertTrue(url.startswith(f"{REPOSITORY_URL}/issues/new?"))
        self.assertIn(__version__, url)
        self.assertIn("sample+error%3A+timeout", url)
        self.assertIn("Privacy+check", url)
        self.assertIn("import.xml", url)

    def test_help_buttons_open_expected_github_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            window = ExportWindow(Path(directory) / "settings.json")
            self.addCleanup(window.close)
            window.log.setPlainText("sensitive test log")
            with patch("opc_ua_export_app.QDesktopServices.openUrl") as open_url:
                window._open_readme()
                opened = open_url.call_args.args[0].toString()
                self.assertEqual(opened, f"{REPOSITORY_URL}/blob/main/README.md")

                with patch(
                    "opc_ua_export_app.QMessageBox.warning",
                    return_value=QMessageBox.StandardButton.Cancel,
                ):
                    window._open_issue()
                self.assertEqual(open_url.call_count, 1)

                with patch(
                    "opc_ua_export_app.QMessageBox.warning",
                    return_value=QMessageBox.StandardButton.Yes,
                ):
                    window._open_issue()
                opened = open_url.call_args.args[0].toString()
                self.assertIn(f"{REPOSITORY_URL}/issues/new?", opened)
                self.assertIn("sensitive+test+log", opened)
                self.assertIn(__version__, opened)
                self.assertEqual(open_url.call_count, 2)

    def test_latest_export_folder_actions_use_created_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "tia_hmi_latest.xlsx"
            workbook.write_bytes(b"test workbook")
            window = ExportWindow(root / "settings.json")
            self.addCleanup(window.close)

            self.assertFalse(window.copy_export_path_button.isEnabled())
            self.assertFalse(window.open_export_folder_button.isEnabled())

            window._show_progress(f"TIA import workbook: {workbook}")
            window._export_completed(0)

            self.assertTrue(window.copy_export_path_button.isEnabled())
            self.assertTrue(window.open_export_folder_button.isEnabled())

            window._copy_latest_export_folder()
            self.assertEqual(Path(QApplication.clipboard().text()), workbook.resolve().parent)

            with patch("opc_ua_export_app.QProcess.startDetached", return_value=True) as start_process:
                window._open_latest_export_folder()
            start_process.assert_called_once_with("explorer.exe", ["/select,", str(workbook.resolve())])

    def test_tia_workbook_format_is_fixed_in_source(self):
        self.assertEqual(len(TIA_HEADERS), 40)
        self.assertEqual(TIA_HEADERS[:9], [
            "Name", "Path", "Connection", "PLC tag", "DataType",
            "HMI DataType", "Length", "Access Method", "Address",
        ])
        self.assertEqual(TIA_SUBSTITUTE_HEADERS, ["HMI Tag name", "Substitute Value Usage"])


if __name__ == "__main__":
    unittest.main()

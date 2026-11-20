import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook, load_workbook
from PySide6.QtWidgets import QApplication

from opc_ua_export import BASE_DIR, DEFAULT_TEMPLATE
from opc_ua_export_app import ExportWindow


class ExportWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_requires_acknowledgement_for_unencrypted_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "template.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Hmi Tags"
            sheet.append(["Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address"])
            sheet.append(["example", "connection", "Int32", "DInt", 4, "Absolute access", "ns=urn:test;s=example"])
            workbook.save(workbook_path)

            window = ExportWindow(Path(directory) / "settings.json")
            self.addCleanup(window.close)
            window.endpoint.setText("opc.tcp://localhost:4840")
            window.connection.setText("test_connection")
            window.anonymous.setChecked(True)
            window.template.setText(str(workbook_path))
            window.example_tag.setText("example")
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
            self.assertEqual(window.example_tag.text(), "ExampleTag")

    def test_bundled_generic_workbook_is_sanitized_and_uses_tia_schema(self):
        self.assertEqual(DEFAULT_TEMPLATE, BASE_DIR / "generic_tia_hmi_template.xlsx")
        workbook = load_workbook(DEFAULT_TEMPLATE, read_only=True, data_only=True)
        try:
            self.assertEqual(workbook.sheetnames, ["Hmi Tags", "Substitute Value Usage"])
            sheet = workbook["Hmi Tags"]
            headers = list(next(sheet.iter_rows(min_row=1, max_row=1, values_only=True)))
            example = list(next(sheet.iter_rows(min_row=2, max_row=2, values_only=True)))
            self.assertEqual(len(headers), 40)
            self.assertEqual(sheet.max_row, 2)
            self.assertEqual(example[headers.index("Name")], "ExampleTag")
            self.assertEqual(example[headers.index("Connection")], "ExampleConnection")
            self.assertEqual(
                example[headers.index("Address")],
                "ns=http://www.siemens.com/simatic-s7-opcua;s=ExampleVariable",
            )
            self.assertEqual(example[headers.index("DataType")], "Int32")
            self.assertEqual(example[headers.index("HMI DataType")], "DInt")
        finally:
            workbook.close()


if __name__ == "__main__":
    unittest.main()

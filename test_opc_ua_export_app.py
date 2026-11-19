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

            window = ExportWindow()
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

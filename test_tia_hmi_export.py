import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from opc_ua_export import BASE_DIR, tag_name, write_tia_export


class TiaExportTest(unittest.TestCase):
    def test_convert_uses_example_and_skips_unsupported_nodes(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            template = root / "template.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Hmi Tags"
            sheet.append(["Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address"])
            sheet.append(["sample", "my_connection", "Int32", "DInt", 4, "Absolute access", "ns=urn:test;s=old"])
            substitute = workbook.create_sheet("Substitute Value Usage")
            substitute.append(["HMI Tag name", "Substitute Value Usage"])
            substitute.append(["sample", "old"])
            workbook.save(template)
            rows = [
                dict(NodeId='ns=2;s="Unit-1.Setpoint"', NamespaceUri="urn:test", DataType="Int32", DataTypeNodeId="i=6", ValueRank=-1, UserAccessLevel="CurrentRead"),
                dict(NodeId="ns=2;s=other", NamespaceUri="urn:test", DataType="String", DataTypeNodeId="i=12", ValueRank=-1, UserAccessLevel="CurrentRead"),
                dict(NodeId="ns=2;s=array", NamespaceUri="urn:test", DataType="Int32", DataTypeNodeId="i=6", ValueRank=1, UserAccessLevel="CurrentRead"),
                dict(NodeId="ns=2;s=secret", NamespaceUri="urn:test", DataType="Int32", DataTypeNodeId="i=6", ValueRank=-1, UserAccessLevel="CurrentWrite"),
            ]
            output, count, skipped, datatype, connection = write_tia_export(template, "sample", rows, root / "export", "test_connection")
            self.assertEqual((count, datatype, connection), (1, "Int32", "test_connection"))
            self.assertEqual(sum(skipped.values()), 3)
            result = load_workbook(output, data_only=True)
            rows = list(result["Hmi Tags"].values)
            self.assertEqual(rows[1], ("Unit-1_Setpoint", "test_connection", "Int32", "DInt", 4, "Absolute access", 'ns=urn:test;s="Unit-1.Setpoint"'))
            self.assertEqual(result["Substitute Value Usage"].max_row, 1)
            result.close()

    def test_tag_name_replaces_invalid_characters(self):
        identifier = '"Area"."Unit-1"."Control"."Setpoint"'
        self.assertEqual(tag_name(identifier), "Area_Unit-1_Control_Setpoint")
        self.assertEqual(tag_name('"Unit-1.Setpoint"'), "Unit-1_Setpoint")
        self.assertEqual(tag_name("a#b$c*d%e.f/g:h?i[j]k`l~m"), "a_b_c_d_e_f_g_h_i_j_k_l_m")

    def test_multiple_opc_types_use_their_own_tia_mapping(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Hmi Tags"
            sheet.append(["Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address"])
            sheet.append(["sample", "conn", "Int32", "DInt", 4, "Absolute access", "ns=urn:test;s=old"])
            template = root / "template.xlsx"
            workbook.save(template)
            mappings = [
                ("i=1", "Boolean", "Bool", 1),
                ("i=4", "Int16", "Int", 2),
                ("i=5", "UInt16", "UInt", 2),
                ("i=6", "Int32", "DInt", 4),
                ("i=7", "UInt32", "UDInt", 4),
                ("i=10", "Float", "Real", 4),
                ("i=11", "Double", "LReal", 8),
            ]
            rows = [dict(NodeId=f"ns=2;s=tag_{index}", NamespaceUri="urn:test", DataType=datatype,
                         DataTypeNodeId=type_id, ValueRank=-1, UserAccessLevel="CurrentRead")
                    for index, (type_id, datatype, _, _) in enumerate(mappings)]
            rows.append(dict(NodeId="ns=2;s=custom", NamespaceUri="urn:test", DataType="Int32",
                             DataTypeNodeId="ns=2;i=6", ValueRank=-1, UserAccessLevel="CurrentRead"))
            rows.append(dict(NodeId="ns=2;s==Unsafe", NamespaceUri="urn:test", DataType="Boolean",
                             DataTypeNodeId="i=1", ValueRank=-1, UserAccessLevel="CurrentRead"))
            output, count, skipped, _, _ = write_tia_export(template, "sample", rows, root / "export", "test_connection")
            self.assertEqual(count, len(mappings) + 1)
            self.assertEqual(sum(skipped.values()), 1)
            self.assertIn("unsupported data type: Int32 (ns=2;i=6)", skipped)
            result = load_workbook(output, read_only=True, data_only=True)
            result_rows = list(result["Hmi Tags"].values)[1:]
            self.assertEqual([row[2:5] for row in result_rows[:-1]], [(datatype, hmi, length) for _, datatype, hmi, length in mappings])
            self.assertEqual(result_rows[-1][0], "=Unsafe")
            self.assertEqual(result["Hmi Tags"].cell(row=count + 1, column=1).data_type, "s")
            result.close()

    def test_duplicate_names_are_rejected(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Hmi Tags"
            sheet.append(["Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address"])
            sheet.append(["sample", "conn", "Int32", "DInt", 4, "Absolute access", "ns=urn:test;s=old"])
            template = root / "template.xlsx"
            workbook.save(template)
            rows = [
                dict(NodeId=node_id, NamespaceUri="urn:test", DataType="Int32", DataTypeNodeId="i=6", ValueRank=-1, UserAccessLevel="CurrentRead")
                for node_id in ['ns=2;s="Unit-1.Setpoint"', "ns=2;s=Unit-1_Setpoint"]
            ]
            with self.assertRaisesRegex(ValueError, "duplicate tag name"):
                write_tia_export(template, "sample", rows, root / "export", "test_connection")

    def test_rejects_non_opc_example(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Hmi Tags"
            sheet.append(["Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address"])
            sheet.append(["sample", "conn", "Int32", "DInt", 4, "Symbolic access", "<No Value>"])
            template = root / "template.xlsx"
            workbook.save(template)
            with self.assertRaisesRegex(ValueError, "connected OPC UA tag"):
                write_tia_export(template, "sample", [], root / "export", "test_connection")


if __name__ == "__main__":
    unittest.main()
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from opc_ua_export import BASE_DIR, TIA_HEADERS, TIA_NAMESPACE, tag_name, write_tia_export


class TiaExportTest(unittest.TestCase):
    def test_convert_uses_fixed_format_and_skips_unsupported_nodes(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            rows = [
                dict(NodeId='ns=2;s="Unit-1.Setpoint"', NamespaceUri=TIA_NAMESPACE, DataType="Int32", DataTypeNodeId="i=6", ValueRank=-1, UserAccessLevel="CurrentRead"),
                dict(NodeId="ns=2;s=other", NamespaceUri=TIA_NAMESPACE, DataType="String", DataTypeNodeId="i=12", ValueRank=-1, UserAccessLevel="CurrentRead"),
                dict(NodeId="ns=2;s=array", NamespaceUri=TIA_NAMESPACE, DataType="Int32", DataTypeNodeId="i=6", ValueRank=1, UserAccessLevel="CurrentRead"),
                dict(NodeId="ns=2;s=secret", NamespaceUri=TIA_NAMESPACE, DataType="Int32", DataTypeNodeId="i=6", ValueRank=-1, UserAccessLevel="CurrentWrite"),
            ]
            output, count, skipped, namespace, connection = write_tia_export(rows, root / "export", "test_connection")
            self.assertEqual((count, namespace, connection), (1, TIA_NAMESPACE, "test_connection"))
            self.assertEqual(sum(skipped.values()), 3)
            result = load_workbook(output, data_only=True)
            sheet_rows = list(result["Hmi Tags"].values)
            self.assertEqual(sheet_rows[0], tuple(TIA_HEADERS))
            self.assertEqual(sheet_rows[1][0], "Unit-1_Setpoint")
            self.assertEqual(sheet_rows[1][2], "test_connection")
            self.assertEqual(sheet_rows[1][4:9], ("Int32", "DInt", 4, "Absolute access", f'ns={TIA_NAMESPACE};s="Unit-1.Setpoint"'))
            self.assertEqual(result["Substitute Value Usage"].max_row, 1)
            result.close()

    def test_tag_name_replaces_quoted_boundaries_and_unsupported_characters(self):
        identifier = '"dbUnit_QuickChillerFirstFloor_Object"."1210.10-IP1"."Control"."PresetValue"'
        self.assertEqual(tag_name(identifier), "dbUnit_QuickChillerFirstFloor_Object_1210_10-IP1_Control_PresetValue")
        self.assertEqual(tag_name('"Unit-1.Setpoint"'), "Unit-1_Setpoint")
        self.assertEqual(tag_name("a#b$c*d%e.f/g:h?i[j]k`l~m"), "a_b_c_d_e_f_g_h_i_j_k_l_m")

    def test_multiple_opc_types_use_their_own_tia_mapping(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            mappings = [
                ("i=1", "Boolean", "Bool", 1),
                ("i=4", "Int16", "Int", 2),
                ("i=5", "UInt16", "UInt", 2),
                ("i=6", "Int32", "DInt", 4),
                ("i=7", "UInt32", "UDInt", 4),
                ("i=10", "Float", "Real", 4),
                ("i=11", "Double", "LReal", 8),
            ]
            rows = [dict(NodeId=f"ns=2;s=tag_{index}", NamespaceUri=TIA_NAMESPACE, DataType=datatype,
                         DataTypeNodeId=type_id, ValueRank=-1, UserAccessLevel="CurrentRead")
                    for index, (type_id, datatype, _, _) in enumerate(mappings)]
            rows.append(dict(NodeId="ns=2;s=custom", NamespaceUri=TIA_NAMESPACE, DataType="Int32",
                             DataTypeNodeId="ns=2;i=6", ValueRank=-1, UserAccessLevel="CurrentRead"))
            rows.append(dict(NodeId="ns=2;s==Unsafe", NamespaceUri=TIA_NAMESPACE, DataType="Boolean",
                             DataTypeNodeId="i=1", ValueRank=-1, UserAccessLevel="CurrentRead"))
            output, count, skipped, _, _ = write_tia_export(rows, root / "export", "test_connection")
            self.assertEqual(count, len(mappings) + 1)
            self.assertEqual(sum(skipped.values()), 1)
            self.assertIn("unsupported data type: Int32 (ns=2;i=6)", skipped)
            result = load_workbook(output, read_only=True, data_only=True)
            result_rows = list(result["Hmi Tags"].values)[1:]
            self.assertEqual([row[4:7] for row in result_rows[:-1]], [(datatype, hmi, length) for _, datatype, hmi, length in mappings])
            self.assertEqual(result_rows[-1][0], "=Unsafe")
            self.assertEqual(result["Hmi Tags"].cell(row=count + 1, column=1).data_type, "s")
            result.close()

    def test_duplicate_names_are_rejected(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            rows = [
                dict(NodeId=node_id, NamespaceUri=TIA_NAMESPACE, DataType="Int32", DataTypeNodeId="i=6", ValueRank=-1, UserAccessLevel="CurrentRead")
                for node_id in ['ns=2;s="Unit-1/Setpoint"', "ns=2;s=Unit-1_Setpoint"]
            ]
            with self.assertRaisesRegex(ValueError, "duplicate tag name"):
                write_tia_export(rows, root / "export", "test_connection")


if __name__ == "__main__":
    unittest.main()
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asyncua import Client, Server, ua
from openpyxl import Workbook, load_workbook

from opc_ua_export import BASE_DIR, browse_children, collect, main, write_tia_export


class ExportTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_server_and_exports(self):
        server = Server()
        await server.init()
        server.set_endpoint("opc.tcp://127.0.0.1:48939/test/")
        namespace = await server.register_namespace("urn:export:test")
        machine = await server.nodes.objects.add_object(namespace, "Machine")
        variable = await machine.add_variable(ua.NodeId("Temperature", namespace), "Temperature", 23.5)
        await variable.set_writable()
        await machine.add_variable(ua.NodeId("Formula", namespace), "=Unsafe", True)
        async with server:
            async with Client("opc.tcp://127.0.0.1:48939/test/") as client:
                rows, errors, namespaces = await collect(client, machine.nodeid.to_string())
                limited_rows, limited_errors, _ = await collect(client, machine.nodeid.to_string(), limit=1)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(limited_rows), 1)
        self.assertEqual(limited_errors, [])
        temp = next(row for row in rows if row["BrowseName"] == "Temperature")
        self.assertEqual(temp["NodeId"], variable.nodeid.to_string())
        self.assertEqual(temp["NamespaceUri"], "urn:export:test")
        self.assertEqual(temp["DataType"], "Double")
        self.assertIn("CurrentRead", temp["UserAccessLevel"])
        self.assertFalse(temp["Errors"])
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as output:
            template = Path(output) / "template.xlsx"
            sample = Workbook()
            sheet = sample.active
            sheet.title = "Hmi Tags"
            sheet.append(["Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address"])
            sheet.append(["sample", "conn", "Double", "LReal", 8, "Absolute access", "ns=urn:export:test;s=old"])
            sample.save(template)
            xlsx_path, count, skipped, _, _ = write_tia_export(template, "sample", rows, Path(output), "test_connection")
            self.assertEqual(count, 2)
            self.assertEqual(sum(skipped.values()), 0)
            workbook = load_workbook(xlsx_path, read_only=True)
            self.assertEqual(workbook.sheetnames, ["Hmi Tags"])
            excel_rows = list(workbook["Hmi Tags"].values)
            temperature_row = next(row for row in excel_rows if row[0] == "Temperature")
            self.assertEqual(temperature_row[6], "ns=urn:export:test;s=Temperature")
            workbook.close()

    async def test_browse_next_error_is_not_silently_ignored(self):
        first = SimpleNamespace(StatusCode=ua.StatusCode(), References=[], ContinuationPoint=b"next")
        second = SimpleNamespace(StatusCode=ua.StatusCode(ua.StatusCodes.BadUserAccessDenied))
        session = SimpleNamespace(browse=AsyncMock(return_value=[first]), browse_next=AsyncMock(return_value=[second]))
        node = SimpleNamespace(nodeid=ua.NodeId(85), session=session)
        with self.assertRaises(ua.UaStatusCodeError):
            await browse_children(node)

    async def test_main_generates_tia_excel_without_csv(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            server = Server()
            await server.init()
            server.set_endpoint("opc.tcp://127.0.0.1:48940/test/")
            namespace = await server.register_namespace("urn:export:test")
            machine = await server.nodes.objects.add_object(namespace, "Machine")
            await machine.add_variable(ua.NodeId('"Machine"."Ignored"', namespace), "Ignored", "text")
            await machine.add_variable(ua.NodeId('"Machine"."Setpoint"', namespace), "Setpoint", 42, ua.VariantType.Int32)
            await machine.add_variable(ua.NodeId('"Machine"."Second"', namespace), "Second", 43, ua.VariantType.Int32)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Hmi Tags"
            sheet.append(["Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address"])
            sheet.append(["sample", "conn", "Int32", "DInt", 4, "Absolute access", "ns=urn:export:test;s=old"])
            template = root / "template.xlsx"
            workbook.save(template)
            args = ["opc_ua_export.py", "--endpoint", "opc.tcp://127.0.0.1:48940/test/", "--anonymous", "--allow-insecure", "--start-node", machine.nodeid.to_string(), "--tia-template", str(template), "--tia-example-tag", "sample", "--connection", "test_connection", "--limit", "1"]
            output = StringIO()
            progress = []
            output_dir = root / "chosen-export-directory"
            async with server:
                with patch("sys.argv", args), patch("opc_ua_export.BASE_DIR", root), redirect_stdout(output), redirect_stderr(StringIO()):
                    result = await main(progress=progress.append, output_dir=output_dir)
            self.assertEqual(result, 0)
            self.assertIn("Found: 1 eligible tags", progress)
            files = list(output_dir.iterdir())
            self.assertEqual(len(files), 1)
            result_book = load_workbook(files[0], read_only=True)
            row = list(result_book["Hmi Tags"].values)[1]
            self.assertEqual(row[0], "Machine_Setpoint")
            self.assertEqual(row[1], "test_connection")
            self.assertEqual(row[6], 'ns=urn:export:test;s="Machine"."Setpoint"')
            result_book.close()

    async def test_empty_connection_is_rejected_before_browsing(self):
        for connection in ("", "   ", "<internal tag>", "TODO_Connection"):
            with self.subTest(connection=connection):
                with patch("sys.argv", ["opc_ua_export.py", "--tia-template", "template.xlsx", "--tia-example-tag", "sample", "--connection", connection]), patch("opc_ua_export.Client") as client:
                    with self.assertRaisesRegex(ValueError, "TIA connection"):
                        await main()
                    client.assert_not_called()

    async def test_connection_is_requested_when_not_given(self):
        with patch("sys.argv", ["opc_ua_export.py", "--tia-template", "template.xlsx", "--tia-example-tag", "sample"]), patch("builtins.input", return_value=" ") as prompt:
            with self.assertRaisesRegex(ValueError, "TIA connection"):
                await main()
            prompt.assert_called_once_with("Existing TIA connection name: ")


if __name__ == "__main__":
    unittest.main()
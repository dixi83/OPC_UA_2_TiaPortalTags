import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asyncua import Client, Server, ua
from openpyxl import load_workbook

from opc_ua_export import BASE_DIR, TIA_NAMESPACE, browse_children, collect, connect_client, main, write_tia_export


class ExportTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_server_and_exports(self):
        server = Server()
        await server.init()
        server.set_endpoint("opc.tcp://127.0.0.1:48939/test/")
        namespace = await server.register_namespace(TIA_NAMESPACE)
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
        self.assertEqual(temp["NamespaceUri"], TIA_NAMESPACE)
        self.assertEqual(temp["DataType"], "Double")
        self.assertIn("CurrentRead", temp["UserAccessLevel"])
        self.assertFalse(temp["Errors"])
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as output:
            xlsx_path, count, skipped, _, _ = write_tia_export(rows, Path(output), "test_connection")
            self.assertEqual(count, 2)
            self.assertEqual(sum(skipped.values()), 0)
            workbook = load_workbook(xlsx_path, read_only=True)
            try:
                self.assertEqual(workbook.sheetnames, ["Hmi Tags", "Substitute Value Usage"])
                excel_rows = list(workbook["Hmi Tags"].values)
                temperature_row = next(row for row in excel_rows if row[0] == "Temperature")
                self.assertEqual(temperature_row[8], f"ns={TIA_NAMESPACE};s=Temperature")
            finally:
                workbook.close()

    async def test_browse_next_error_is_not_silently_ignored(self):
        first = SimpleNamespace(StatusCode=ua.StatusCode(), References=[], ContinuationPoint=b"next")
        second = SimpleNamespace(StatusCode=ua.StatusCode(ua.StatusCodes.BadUserAccessDenied))
        session = SimpleNamespace(browse=AsyncMock(return_value=[first]), browse_next=AsyncMock(return_value=[second]))
        node = SimpleNamespace(nodeid=ua.NodeId(85), session=session)
        with self.assertRaises(ua.UaStatusCodeError):
            await browse_children(node)

    async def test_connect_retries_a_closed_session_once(self):
        client = SimpleNamespace(
            connect=AsyncMock(
                side_effect=[
                    ua.UaStatusCodeError(ua.StatusCodes.BadSessionClosed),
                    None,
                ]
            )
        )
        messages = []

        await connect_client(client, lambda message, error=False: messages.append((message, error)))

        self.assertEqual(client.connect.await_count, 2)
        self.assertEqual(messages, [
            ("The OPC UA server invalidated the new session; reconnecting once...", True)
        ])

    async def test_connect_does_not_retry_unrelated_server_errors(self):
        client = SimpleNamespace(
            connect=AsyncMock(
                side_effect=ua.UaStatusCodeError(ua.StatusCodes.BadUserAccessDenied)
            )
        )

        with self.assertRaises(ua.UaStatusCodeError):
            await connect_client(client, lambda message, error=False: None)

        client.connect.assert_awaited_once_with()

    async def test_main_generates_tia_excel_without_csv(self):
        (BASE_DIR / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE_DIR / ".tmp") as directory:
            root = Path(directory)
            server = Server()
            await server.init()
            server.set_endpoint("opc.tcp://127.0.0.1:48940/test/")
            namespace = await server.register_namespace(TIA_NAMESPACE)
            machine = await server.nodes.objects.add_object(namespace, "Machine")
            await machine.add_variable(ua.NodeId('"Machine"."Ignored"', namespace), "Ignored", "text")
            await machine.add_variable(ua.NodeId('"Machine"."Setpoint"', namespace), "Setpoint", 42, ua.VariantType.Int32)
            await machine.add_variable(ua.NodeId('"Machine"."Second"', namespace), "Second", 43, ua.VariantType.Int32)
            args = ["opc_ua_export.py", "--endpoint", "opc.tcp://127.0.0.1:48940/test/", "--anonymous", "--allow-insecure", "--start-node", machine.nodeid.to_string(), "--connection", "test_connection", "--limit", "1"]
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
            try:
                self.assertEqual(row[0], "Machine_Setpoint")
                self.assertEqual(row[2], "test_connection")
                self.assertEqual(row[8], f'ns={TIA_NAMESPACE};s="Machine"."Setpoint"')
            finally:
                result_book.close()

    async def test_empty_connection_is_rejected_before_browsing(self):
        for connection in ("", "   ", "<internal tag>", "TODO_Connection"):
            with self.subTest(connection=connection):
                with patch("sys.argv", ["opc_ua_export.py", "--connection", connection]), patch("opc_ua_export.Client") as client:
                    with self.assertRaisesRegex(ValueError, "TIA connection"):
                        await main()
                    client.assert_not_called()

    async def test_connection_is_requested_when_not_given(self):
        with patch("sys.argv", ["opc_ua_export.py"]), patch("builtins.input", return_value=" ") as prompt:
            with self.assertRaisesRegex(ValueError, "TIA connection"):
                await main()
            prompt.assert_called_once_with("Existing TIA connection name: ")


if __name__ == "__main__":
    unittest.main()
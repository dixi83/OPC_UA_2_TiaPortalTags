from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import re
import sys
from collections import Counter, deque
from copy import copy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from asyncua import Client, ua
from openpyxl import load_workbook

from version import __version__


BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DEFAULT_TEMPLATE = BASE_DIR / "generic_tia_hmi_template.xlsx"
# Each mapping stores the OPC UA display name, TIA HMI type, and byte length.
TYPE_MAPPING = {
    ua.NodeId(ua.ObjectIds.Boolean).to_string(): ("Boolean", "Bool", 1),
    ua.NodeId(ua.ObjectIds.Int16).to_string(): ("Int16", "Int", 2),
    ua.NodeId(ua.ObjectIds.UInt16).to_string(): ("UInt16", "UInt", 2),
    ua.NodeId(ua.ObjectIds.Int32).to_string(): ("Int32", "DInt", 4),
    ua.NodeId(ua.ObjectIds.UInt32).to_string(): ("UInt32", "UDInt", 4),
    ua.NodeId(ua.ObjectIds.Float).to_string(): ("Float", "Real", 4),
    ua.NodeId(ua.ObjectIds.Double).to_string(): ("Double", "LReal", 8),
}
REQUIRED_HEADERS = ("Name", "Connection", "DataType", "HMI DataType", "Length", "Access Method", "Address")
HEADERS = [
    "Path", "BrowseName", "DisplayName", "NodeId", "NamespaceUri",
    "DataTypeNodeId", "DataType", "ValueRank", "ArrayDimensions",
    "AccessLevel", "UserAccessLevel", "Description", "Errors",
]
ATTRIBUTES = [
    ua.AttributeIds.DataType, ua.AttributeIds.ValueRank,
    ua.AttributeIds.UserAccessLevel,
]


def attribute_value(result):
    """Decode an attribute result while preserving unsuccessful OPC UA status codes."""
    """Decode an OPC UA attribute result without hiding bad status codes."""
    if result.StatusCode is None or not result.StatusCode.is_good():
        return None, str(result.StatusCode)
    return (result.Value.Value if result.Value is not None else None), ""


def access_text(value):
    """Format the access-level bit field used to exclude unreadable variables."""
    """Format the access-level bit field for export filtering and diagnostics."""
    if value is None:
        return ""
    return ", ".join(sorted(item.name for item in ua.AccessLevel.parse_bitfield(value)))


async def browse_children(node):
    """Browse one node and follow every continuation point returned by the server."""
    description = ua.BrowseDescription()
    description.NodeId = node.nodeid
    description.BrowseDirection = ua.BrowseDirection.Forward
    description.ReferenceTypeId = ua.NodeId(ua.ObjectIds.HierarchicalReferences)
    description.IncludeSubtypes = True
    description.ResultMask = ua.BrowseResultMask.All
    parameters = ua.BrowseParameters()
    parameters.NodesToBrowse = [description]
    parameters.RequestedMaxReferencesPerNode = 0
    results = await node.session.browse(parameters)
    if not results:
        raise RuntimeError("Browse returned no result")
    references = []
    while True:
        result = results[0]
        result.StatusCode.check()
        references.extend(result.References or [])
        if not result.ContinuationPoint:
            return references
        next_parameters = ua.BrowseNextParameters()
        next_parameters.ContinuationPoints = [result.ContinuationPoint]
        next_parameters.ReleaseContinuationPoints = False
        results = await node.session.browse_next(next_parameters)
        if not results:
            raise RuntimeError("BrowseNext returned no result")


async def variable_row(client, node, path, browse_name, display_name, namespaces, datatype_cache):
    """Read only the metadata needed to classify a variable; never read its value."""
    errors = []
    row = {header: "" for header in HEADERS}
    row.update({
        "Path": path, "BrowseName": browse_name, "DisplayName": display_name,
        "NodeId": node.nodeid.to_string(),
        "NamespaceUri": namespaces[node.nodeid.NamespaceIndex]
        if node.nodeid.NamespaceIndex < len(namespaces) else "",
    })
    try:
        results = await node.read_attributes(ATTRIBUTES)
        if len(results) != len(ATTRIBUTES):
            raise RuntimeError("Incomplete attribute result")
        values = []
        for attribute, result in zip(ATTRIBUTES, results):
            value, error = attribute_value(result)
            values.append(value)
            if error:
                errors.append(f"{attribute.name}: {error}")
        datatype, rank, user_access = values
        if datatype is not None:
            row["DataTypeNodeId"] = datatype.to_string()
            datatype_id = datatype.to_string()
            if datatype_id not in datatype_cache:
                try:
                    datatype_cache[datatype_id] = (await client.get_node(datatype).read_browse_name()).Name
                except Exception as exc:
                    errors.append(f"DataType name: {exc}")
            row["DataType"] = datatype_cache.get(datatype_id, "")
        row["ValueRank"] = "" if rank is None else int(rank)
        row["UserAccessLevel"] = access_text(user_access)
    except Exception as exc:
        errors.append(f"Attributes: {exc}")
    row["Errors"] = " | ".join(errors)
    return row


async def collect(client, start_node, limit=None, eligible=None, progress=None):
    """Walk visible hierarchical references and periodically report browse counts."""
    report = progress or (lambda message: print(message, flush=True))
    namespaces = await client.get_namespace_array()
    root = client.get_node(start_node) if start_node else client.nodes.objects
    root_name = (await root.read_browse_name()).Name or "Objects"
    queue = deque([(root, root_name, None)])
    visited = set()
    rows = []
    errors = []
    datatype_cache = {}
    eligible_count = 0
    while queue:
        node, path, reference = queue.popleft()
        node_id = node.nodeid.to_string()
        if node_id in visited:
            continue
        visited.add(node_id)
        try:
            node_class = reference.NodeClass if reference else await node.read_node_class()
            if node_class == ua.NodeClass.Variable:
                browse_name = reference.BrowseName.Name if reference else root_name
                display_name = reference.DisplayName.Text if reference else root_name
                row = await variable_row(client, node, path, browse_name, display_name, namespaces, datatype_cache)
                rows.append(row)
                if eligible is None or eligible(row):
                    eligible_count += 1
                if limit is not None and eligible_count >= limit:
                    break
            for child in await browse_children(node):
                child_id = child.NodeId
                if getattr(child_id, "ServerIndex", 0) or getattr(child_id, "NamespaceUri", None):
                    errors.append((path, node_id, f"Skipped external reference: {child_id}"))
                    continue
                child_name = child.BrowseName.Name or child_id.to_string()
                queue.append((client.get_node(child_id), path + "/" + child_name, child))
        except Exception as exc:
            errors.append((path, node_id, str(exc)))
        if len(visited) % 100 == 0:
            report(f"Browsed: {len(visited)} nodes, {len(rows)} variables, {eligible_count} eligible tags")
    report(f"Found: {eligible_count} eligible tags")
    return rows, errors, namespaces


def tag_name(identifier):
    """Normalize a string NodeId identifier to TIA's accepted tag-name characters."""
    """Normalize a string NodeId identifier to the accepted TIA tag-name alphabet."""
    name = identifier.replace('"."', '_').replace('"', '')
    return name.translate(str.maketrans({character: "_" for character in "#$*%./:?[]`~"}))


def get_example(sheet, example_name):
    """Validate the selected HMI example tag and return its reusable row data."""
    headers = [cell.value for cell in sheet[1]]
    nonempty_headers = [header for header in headers if header is not None]
    if len(set(nonempty_headers)) != len(nonempty_headers):
        raise ValueError("The workbook contains duplicate column names.")
    if any(header not in headers for header in REQUIRED_HEADERS):
        raise ValueError("The workbook is missing a required HMI column.")
    columns = {header: index for index, header in enumerate(headers) if header is not None}
    matches = [row for row in sheet.iter_rows(min_row=2) if row[columns["Name"]].value == example_name]
    if len(matches) != 1:
        raise ValueError("Example tag was not found or is not unique.")
    example = matches[0]
    values = [cell.value for cell in example]
    sample_address = values[columns["Address"]]
    connection = values[columns["Connection"]]
    datatype = values[columns["DataType"]]
    if (not isinstance(sample_address, str) or not sample_address.startswith("ns=")
            or ";s=" not in sample_address or not connection or connection == "<No Value>"
            or values[columns["Access Method"]] != "Absolute access"):
        raise ValueError("The example tag must be a connected OPC UA tag with a string NodeId.")
    namespace = sample_address[3:].split(";s=", 1)[0]
    if not namespace or not datatype or datatype == "<No Value>":
        raise ValueError("The example tag is missing its namespace or data type.")
    return columns, example, values, namespace, datatype, connection


def skip_reason(record, namespace):
    """Return a reason when a variable does not meet the supported export criteria."""
    if record["NamespaceUri"] != namespace:
        return "different namespace"
    if record.get("DataTypeNodeId") not in TYPE_MAPPING:
        return f"unsupported data type: {record.get('DataType') or 'unknown'} ({record.get('DataTypeNodeId') or 'unknown'})"
    if str(record["ValueRank"]) != "-1":
        return "array or unknown dimensions"
    if "CurrentRead" not in record["UserAccessLevel"].split(", "):
        return "read access not confirmed"
    if not re.fullmatch(r"(?:ns=\d+;)?s=(.+)", record["NodeId"], re.DOTALL):
        return "NodeId is not a string identifier"
    return None


def write_tia_export(template_path, example_name, rows, output_dir, connection_name):
    """Copy supported tags into a new workbook based on a user-selected example row."""
    connection_name = connection_name.strip()
    if not connection_name or connection_name.casefold() in {"<internal tag>", "<no value>", "todo_connection"}:
        raise ValueError("Enter a valid existing TIA connection name.")
    workbook = load_workbook(template_path)
    try:
        if "Hmi Tags" not in workbook:
            raise ValueError("The workbook has no 'Hmi Tags' worksheet.")
        sheet = workbook["Hmi Tags"]
        columns, example, values, namespace, datatype, connection = get_example(sheet, example_name)
        selected = []
        skipped = Counter()
        names = set()
        for record in rows:
            match = re.fullmatch(r"(?:ns=\d+;)?s=(.+)", record["NodeId"], re.DOTALL)
            reason = skip_reason(record, namespace)
            if reason:
                skipped[reason] += 1
            else:
                assert match is not None
                identifier = match.group(1)
                name = tag_name(identifier)
                if not name or name.casefold() in names:
                        raise ValueError(f"Empty or duplicate tag name: {name!r}; check the NodeIds.")
                names.add(name.casefold())
                selected.append((name, "ns=" + namespace + ";s=" + identifier, TYPE_MAPPING[record["DataTypeNodeId"]]))
        if not selected:
            raise ValueError("No matching readable tags were found; no file was created. Try --limit 0 or a higher limit.")
        styles = [copy(cell._style) for cell in example]
        sheet.delete_rows(2, sheet.max_row - 1)
        for name, address, type_values in selected:
            row_values = list(values)
            row_values[columns["Name"]] = name
            row_values[columns["Connection"]] = connection_name
            row_values[columns["Address"]] = address
            row_values[columns["DataType"]], row_values[columns["HMI DataType"]], row_values[columns["Length"]] = type_values
            sheet.append(row_values)
            for cell, style in zip(sheet[sheet.max_row], styles):
                cell._style = copy(style)
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        # The template's substitute-value references are specific to its original tags.
        for other in workbook:
            if other.title == "Substitute Value Usage" and other.max_row > 1:
                other.delete_rows(2, other.max_row - 1)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"tia_hmi_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx"
        workbook.save(output_path)
        return output_path, len(selected), skipped, datatype, connection_name
    finally:
        workbook.close()


def parse_args():
    """Build the CLI parser; workbook and example selection are intentionally explicit."""
    parser = argparse.ArgumentParser(description="Export OPC UA variables to a TIA HMI workbook.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--endpoint", help="OPC UA endpoint, for example opc.tcp://host:4840")
    authentication = parser.add_mutually_exclusive_group()
    authentication.add_argument("--user", help="Username; prompted when omitted")
    authentication.add_argument("--anonymous", action="store_true", help="Connect anonymously")
    parser.add_argument("--security", help="Policy,Mode,client certificate,private key,server certificate")
    parser.add_argument("--allow-insecure", action="store_true", help="Explicitly allow a connection without channel security")
    parser.add_argument("--start-node", help="Optional starting NodeId; defaults to Objects")
    parser.add_argument("--limit", type=int, default=100, help="Maximum suitable tags (default: 100; 0: unlimited)")
    parser.add_argument("--tia-template", type=Path, default=DEFAULT_TEMPLATE, help="TIA HMI workbook (default: generic template beside the application)")
    parser.add_argument("--tia-example-tag", default="ExampleTag", help="Name of the OPC UA example tag (default: ExampleTag)")
    parser.add_argument("--connection", help="Existing TIA HMI connection name; prompted when omitted")
    parser.add_argument("--timeout", type=float, default=10, help="Timeout per server request in seconds")
    return parser.parse_args()


async def main(args=None, password=None, progress=None, output_dir=None):
    """Run the shared CLI/GUI export flow, accepting optional GUI callbacks and inputs."""
    args = args or parse_args()

    def report(message, error=False):
        if progress:
            progress(message)
        else:
            print(message, file=sys.stderr if error else sys.stdout, flush=True)

    connection_name = args.connection if args.connection is not None else input("Existing TIA connection name: ")
    connection_name = connection_name.strip()
    if not connection_name or connection_name.casefold() in {"<internal tag>", "<no value>", "todo_connection"}:
        raise ValueError("Enter a valid existing TIA connection name.")
    if not args.tia_template.is_file():
        raise ValueError(f"TIA workbook not found: {args.tia_template}")
    workbook = load_workbook(args.tia_template, read_only=True)
    try:
        if "Hmi Tags" not in workbook:
            raise ValueError("The workbook has no 'Hmi Tags' worksheet.")
        _, _, _, namespace, datatype, _ = get_example(workbook["Hmi Tags"], args.tia_example_tag)
    finally:
        workbook.close()
    endpoint = args.endpoint or input("OPC UA endpoint (opc.tcp://...): ").strip()
    parsed = urlparse(endpoint)
    if parsed.scheme != "opc.tcp" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an opc.tcp:// endpoint without a username or password in the URL.")
    if args.timeout <= 0:
        raise ValueError("Timeout must be greater than zero.")
    if args.limit < 0:
        raise ValueError("The limit must be zero or greater.")
    if not args.security and not args.allow_insecure:
        raise ValueError("Provide --security or explicitly use --allow-insecure for an unencrypted connection.")
    client = Client(endpoint, timeout=args.timeout)
    if not args.anonymous:
        username = args.user or input("Username: ").strip()
        if not username:
            raise ValueError("Username cannot be empty; use --anonymous for anonymous access.")
        client.set_user(username)
        client.set_password(password if password is not None else getpass.getpass("Password: "))
    if args.security:
        parts = args.security.split(",")
        if len(parts) != 5 or any(not part for part in parts):
            raise ValueError("--security requires policy,mode,client-certificate,private-key,server-certificate.")
        if parts[0] != "Basic256Sha256" or parts[1] not in ("Sign", "SignAndEncrypt"):
            raise ValueError("Use the Basic256Sha256 policy and the Sign or SignAndEncrypt mode.")
        await client.set_security_string(args.security)
    else:
        report("WARNING: the connection is unencrypted; credentials may be exposed on the network.", error=True)
    report("Connecting and browsing the address space...")
    async with client:
        rows, errors, namespaces = await collect(
            client,
            args.start_node,
            args.limit or None,
            lambda row: skip_reason(row, namespace) is None,
            progress=report,
        )
    report(f"Complete: {len(rows)} variables, {len(errors)} browse errors.")
    for path, node_id, error in errors:
        report(f"Browse error {path} ({node_id}): {error}", error=True)
    attribute_errors = Counter(row["Errors"] for row in rows if row["Errors"])
    for error, count in attribute_errors.items():
        report(f"Attribute error on {count} variables: {error}", error=True)
    target_dir = output_dir if output_dir is not None else BASE_DIR / "export"
    tia_path, count, skipped, datatype, connection = write_tia_export(args.tia_template, args.tia_example_tag, rows, target_dir, connection_name)
    report(f"TIA import workbook: {tia_path}")
    report(f"TIA tags: {count}; connection: {connection}")
    if args.limit and count >= args.limit:
        report(f"Limit of {args.limit} TIA tags reached; the full address space was not browsed.")
    if skipped:
        report("Skipped from TIA export: " + ", ".join(f"{reason}: {number}" for reason, number in skipped.items()))
    if errors or any(row["Errors"] for row in rows):
        report("WARNING: errors occurred; the export may be incomplete.", error=True)
        return 2
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("Cancelled; no complete export was created.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
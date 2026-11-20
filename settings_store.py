from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


FORMAT_VERSION = 1
SETTING_KEYS = {
    "endpoint",
    "connection",
    "anonymous",
    "username",
    "security_mode",
    "policy",
    "client_cert",
    "client_key",
    "server_cert",
    "template",
    "example_tag",
    "output_dir",
    "start_node",
    "limit",
    "timeout",
}
STRING_KEYS = SETTING_KEYS - {"anonymous", "limit", "timeout"}


def default_settings_path() -> Path:
    """Return the per-user settings path, outside the replaceable application folder."""
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / ".config"
    return root / "OPC_UA_TIA_Export" / "settings.json"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Load only supported, correctly typed fields; corrupt files are treated as empty."""
    settings_path = path or default_settings_path()
    try:
        document = json.loads(settings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(document, dict):
        return {}

    stored = document.get("settings", document)
    if not isinstance(stored, dict):
        return {}

    clean: dict[str, Any] = {}
    for key in STRING_KEYS:
        value = stored.get(key)
        if isinstance(value, str):
            clean[key] = value
    if isinstance(stored.get("anonymous"), bool):
        clean["anonymous"] = stored["anonymous"]
    limit = stored.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
        clean["limit"] = limit
    timeout = stored.get("timeout")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
        clean["timeout"] = float(timeout)
    return clean


def save_settings(settings: dict[str, Any], path: Path | None = None) -> Path:
    """Atomically persist supported non-secret settings for the current Windows user."""
    settings_path = path or default_settings_path()
    clean = {key: value for key, value in settings.items() if key in SETTING_KEYS}
    document = {"format_version": FORMAT_VERSION, "settings": clean}
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_path.replace(settings_path)
    return settings_path

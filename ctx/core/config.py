import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "ctx"
CONFIG_PATH = CONFIG_DIR / "config.json"

_DEFAULTS: dict[str, Any] = {
    "colors": {
        "user": "#3b82f6",
        "assistant": "#f97316",
        "system": "#737373",
        "context": "#22c55e",
    },
    "ui": {
        "truncation_lines": {
            "user": 2,
            "assistant": 2,
            "context": 2,
            "system": 1,
            "application": 1,
        }
    },
}


def get_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                user_config = json.load(f)
            merged = _DEFAULTS.copy()
            merged.update(user_config)
            if "colors" in user_config:
                merged["colors"] = {**_DEFAULTS["colors"], **user_config["colors"]}
            if "ui" in user_config:
                merged["ui"] = {**_DEFAULTS["ui"], **user_config["ui"]}
                if "truncation_lines" in user_config.get("ui", {}):
                    merged["ui"]["truncation_lines"] = {
                        **_DEFAULTS["ui"]["truncation_lines"],
                        **user_config["ui"]["truncation_lines"],
                    }
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULTS.copy()

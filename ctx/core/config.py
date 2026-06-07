import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ctx"
CONFIG_PATH = CONFIG_DIR / "config.json"

_DEFAULTS = {
    "colors": {
        "user": "#3b82f6",
        "assistant": "#f97316",
        "system": "#737373",
        "context": "#22c55e",
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
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULTS.copy()
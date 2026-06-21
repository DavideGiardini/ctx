import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ctx"
CONFIG_PATH = CONFIG_DIR / "config.json"

_DEFAULTS: dict[str, dict] = {
    "colors": {
        "user": "#3b82f6",
        "assistant": "#f97316",
        "system": "#737373",
        "context": "#22c55e",
    },
    "ui": {
        # Max lines a node occupies in the right-pane conversation graph before
        # it truncates. A value of "auto" disables truncation for that role.
        # Config keys mirror the Product Concept (section 7.7); the UI maps
        # "human" -> the "user" role.
        "truncation_lines": {
            "human": 2,
            "assistant": 2,
            "context": 2,
            "system": 1,
        },
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
                if "truncation_lines" in user_config["ui"]:
                    merged["ui"]["truncation_lines"] = {
                        **_DEFAULTS["ui"]["truncation_lines"],
                        **user_config["ui"]["truncation_lines"],
                    }
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULTS.copy()

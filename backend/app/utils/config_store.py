"""Runtime configuration store behind ``/api/admin/config``.

``settings.yaml`` holds the committed defaults; ``settings.local.yaml``
(git-ignored) holds operator overrides.  Reads return the deep-merge of the
two, writes deep-merge a patch into the overrides file.
"""

import threading
from copy import deepcopy
from typing import Any

import yaml

from app.config import settings

_lock = threading.Lock()


def _read_yaml(path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return data


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` with ``patch`` merged in; nested dicts merge, everything else replaces."""
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_defaults() -> dict[str, Any]:
    return _read_yaml(settings.resolve_path(settings.SETTINGS_FILE))


def load_overrides() -> dict[str, Any]:
    return _read_yaml(settings.resolve_path(settings.SETTINGS_OVERRIDES_FILE))


def get_config() -> dict[str, Any]:
    """Effective configuration: defaults with operator overrides applied."""
    with _lock:
        return deep_merge(load_defaults(), load_overrides())


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the overrides file and return the new effective config.

    Only top-level sections that exist in ``settings.yaml`` may be patched, so a
    typo cannot silently create a section nothing reads.
    """
    defaults = load_defaults()
    unknown = sorted(set(patch) - set(defaults))
    if unknown:
        raise KeyError("Unknown configuration section(s): " + ", ".join(unknown))

    with _lock:
        overrides = deep_merge(load_overrides(), patch)
        path = settings.resolve_path(settings.SETTINGS_OVERRIDES_FILE)
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(overrides, handle, sort_keys=False)
        return deep_merge(defaults, overrides)

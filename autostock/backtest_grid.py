from __future__ import annotations

from dataclasses import is_dataclass, replace
from itertools import product
from pathlib import Path
from typing import Any

import yaml

from autostock.config import AppConfig

DEFAULT_SCENARIOS: list[dict[str, str]] = [
    {"name": "5min", "duration": "60 D", "bar_size": "5 mins"},
    {"name": "1d", "duration": "2 Y", "bar_size": "1 day"},
]


def load_grid_spec(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("grid config must be a YAML object")
    return raw


def normalize_parameter_grid(raw_grid: dict[str, Any]) -> dict[str, list[Any]]:
    params = raw_grid.get("parameters", {})
    if not isinstance(params, dict) or not params:
        raise ValueError("grid.parameters is required and must be a non-empty mapping")
    normalized: dict[str, list[Any]] = {}
    for key, values in params.items():
        path = str(key).strip()
        if not path:
            raise ValueError("grid parameter key cannot be empty")
        if isinstance(values, list):
            if not values:
                raise ValueError(f"grid parameter {path} has empty value list")
            normalized[path] = list(values)
        else:
            normalized[path] = [values]
    return normalized


def generate_grid_overrides(parameter_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(parameter_grid.keys())
    value_lists = [parameter_grid[k] for k in keys]
    out: list[dict[str, Any]] = []
    for combo in product(*value_lists):
        out.append({k: v for k, v in zip(keys, combo)})
    return out


def grid_scenarios(raw_grid: dict[str, Any]) -> list[dict[str, str]]:
    raw = raw_grid.get("scenarios")
    if raw is None:
        return list(DEFAULT_SCENARIOS)
    if not isinstance(raw, list) or not raw:
        raise ValueError("grid.scenarios must be a non-empty list when provided")
    out: list[dict[str, str]] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"grid.scenarios[{i}] must be an object")
        name = str(item.get("name", "")).strip() or f"scenario_{i}"
        duration = str(item.get("duration", "")).strip()
        bar_size = str(item.get("bar_size", "")).strip()
        if not duration or not bar_size:
            raise ValueError(f"grid.scenarios[{i}] requires duration and bar_size")
        out.append({"name": name, "duration": duration, "bar_size": bar_size})
    return out


def apply_overrides(config: AppConfig, overrides: dict[str, Any]) -> AppConfig:
    updated: AppConfig = config
    for dotted_path, value in overrides.items():
        parts = [p for p in str(dotted_path).split(".") if p]
        if not parts:
            raise ValueError("override path cannot be empty")
        updated = _replace_by_path(updated, parts, value)
    return updated


def _replace_by_path(obj: Any, parts: list[str], value: Any) -> Any:
    if not is_dataclass(obj):
        raise ValueError(f"cannot set {'.'.join(parts)}: target is not a dataclass")
    key = parts[0]
    if not hasattr(obj, key):
        raise ValueError(f"unknown config field: {key}")
    if len(parts) == 1:
        return replace(obj, **{key: value})
    child = getattr(obj, key)
    new_child = _replace_by_path(child, parts[1:], value)
    return replace(obj, **{key: new_child})


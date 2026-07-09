from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config/user.yaml")
DEFAULT_TEMPLATE_CONFIG_PATH = Path("config/default.yaml")
DEFAULT_CONFIG: dict[str, Any] = {
    "database_path": "data/portfolio.db",
    "report_dir": "reports",
    "base_currency": "USD",
    "currency_conversion": {
        "rates_to_base": {
            "USD": 1,
            "INR": 0.012,
        }
    },
    "risk_profile": {
        "name": "moderate_growth",
        "max_single_stock_pct": 10,
        "max_crypto_pct": 10,
        "watch_single_stock_pct": 7,
    },
    "reporting": {
        "output_currency": "USD",
        "top_movers_limit": 5,
        "monthly_underperformance_threshold_pct": -20,
    },
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        config_path = DEFAULT_TEMPLATE_CONFIG_PATH
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        import yaml
    except ImportError:
        return _load_minimal_yaml(config_path)
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return _deep_merge(DEFAULT_CONFIG, loaded)


def database_path(config: dict[str, Any]) -> Path:
    return Path(config.get("database_path", "data/portfolio.db"))


def report_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("report_dir", "reports"))


def _load_minimal_yaml(path: Path) -> dict[str, Any]:
    """Small fallback parser for the default config shape.

    It supports top-level scalar keys and one-level nested mappings. Install
    PyYAML for full YAML support.
    """
    result = dict(DEFAULT_CONFIG)
    current_section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith(" ") and ":" in raw_line:
            key, value = raw_line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                result[key] = _coerce_scalar(value)
                current_section = None
            else:
                result.setdefault(key, {})
                current_section = key
        elif current_section and ":" in raw_line:
            key, value = raw_line.split(":", 1)
            target = result.setdefault(current_section, {})
            if isinstance(target, dict):
                target[key.strip()] = _coerce_scalar(value.strip())
    return result


def _coerce_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged

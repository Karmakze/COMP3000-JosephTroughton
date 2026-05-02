"""
Shared runtime config for thresholds/window sizes.

Values are loaded from Code/.env if present, then from process env.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
_ENV_LOADED = False


def _load_env_file_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _get_float(name: str, default: float, *, low: float | None = None, high: float | None = None) -> float:
    _load_env_file_once()
    raw = os.getenv(name)
    try:
        val = float(raw) if raw is not None else float(default)
    except (ValueError, TypeError):
        val = float(default)
    if low is not None and val < low:
        val = low
    if high is not None and val > high:
        val = high
    return val


def _get_int(name: str, default: int, *, low: int | None = None, high: int | None = None) -> int:
    _load_env_file_once()
    raw = os.getenv(name)
    try:
        val = int(raw) if raw is not None else int(default)
    except (ValueError, TypeError):
        val = int(default)
    if low is not None and val < low:
        val = low
    if high is not None and val > high:
        val = high
    return val


def _get_str(name: str, default: str = "") -> str:
    _load_env_file_once()
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip()


# Ingestion/model inference
INGEST_THRESHOLD_DEFAULT = _get_float("CS2CD_INGEST_THRESHOLD", 0.5, low=0.0, high=1.0)

# Per-kill score smoothing around score tick
KILL_SCORE_WINDOW_TICKS_DEFAULT = _get_int("CS2CD_KILL_SCORE_WINDOW_TICKS", 2, low=0)

# Engagement/TTD logic
FORGET_WINDOW_SECONDS_DEFAULT = _get_float("CS2CD_FORGET_WINDOW_SECONDS", 4.0, low=0.1)

# UI kill-window plot defaults
KILL_WINDOW_BASELINE_TICKS_DEFAULT = _get_int("CS2CD_KILL_WINDOW_BASELINE_TICKS", 20, low=1)
KILL_WINDOW_POST_DEATH_TICKS_DEFAULT = _get_int("CS2CD_KILL_WINDOW_POST_DEATH_TICKS", 20, low=0)
KILL_WINDOW_SEARCH_BACK_TICKS_DEFAULT = _get_int("CS2CD_KILL_WINDOW_SEARCH_BACK_TICKS", 256, low=1)

# File dialog defaults
DEFAULT_DEMO_DIR = _get_str("CS2CD_DEFAULT_DEMO_DIR", "")

"""Remembered choices (tool colors, last font sizes, folders): one place for every feature's settings."""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings


def store() -> QSettings:
    return QSettings("pdfdesk", "pdfdesk")


def get(key: str, default=None):
    v = store().value(key)
    return default if v is None else v


def get_float(key: str, default: float) -> float:
    try:
        return float(store().value(key, default))
    except (TypeError, ValueError):
        return default


def get_json(key: str, default):
    try:
        return json.loads(store().value(key, json.dumps(default)))
    except (TypeError, ValueError):
        return default


def put(key: str, value):
    store().setValue(key, value)


def put_json(key: str, value):
    store().setValue(key, json.dumps(value))

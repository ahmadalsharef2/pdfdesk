"""Command registry: GUI, CLI, batch and Action Wizard all call commands by name."""
from __future__ import annotations

from typing import Callable

COMMANDS: dict[str, Callable] = {}


def command(name: str):
    def deco(fn):
        COMMANDS[name] = fn
        fn.command_name = name
        return fn
    return deco


def run(name: str, /, *args, **kwargs):
    import pdfdesk.commands  # noqa: F401  (registers everything)
    if name not in COMMANDS:
        raise KeyError(f"unknown command: {name}")
    return COMMANDS[name](*args, **kwargs)

"""pdfdesk [--combine | --convert] [files…]   opens the window (or hands the files to the open one)
pdfdesk run <Command> in.pdf -o out.pdf [--key value …]   runs one command without a window
pdfdesk commands                                       lists the commands"""
from __future__ import annotations

import argparse
import json
import os
import sys

ACTIONS = {"--combine": "combine", "--convert": "convert"}


def _coerce(v: str):
    try:
        return json.loads(v)
    except ValueError:
        return v


def _run_command(argv) -> int:
    import pymupdf

    from .commands import COMMANDS, run
    from .core import license
    from .gui import prefs
    if not license.valid(os.environ.get("PDFDESK_KEY") or prefs.get("product_key")):
        print("pdfdesk needs its product key: start the window once and enter it, or set PDFDESK_KEY.", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="pdfdesk run")
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--output")
    args, rest = ap.parse_known_args(argv)
    kw = {rest[i].lstrip("-").replace("-", "_"): _coerce(rest[i + 1]) for i in range(0, len(rest), 2)}
    doc = pymupdf.open(args.input) if args.input else None
    res = run(args.command, doc, **kw) if doc is not None else run(args.command, **kw)
    out = res if isinstance(res, pymupdf.Document) else doc
    if args.output and out is not None:
        out.save(args.output, garbage=4, deflate=True, clean=True)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run"]:
        return _run_command(argv[1:])
    if argv[:1] == ["commands"]:
        from .commands import COMMANDS
        print("\n".join(sorted(COMMANDS)))
        return 0
    action = next((ACTIONS[a] for a in argv if a in ACTIONS), "open")
    files = [a for a in argv if a not in ACTIONS and os.path.isfile(a)]
    from . import instance
    if files and instance.hand_off(action, files):      # already running: give it the files, skip start-up
        return 0
    lock = instance.become_primary()
    if lock is None:                                     # another launch of the same click is starting the window
        return 0 if instance.hand_off(action, files, wait=30) else 1
    from .gui.app import launch
    return launch(action, files, lock)


if __name__ == "__main__":
    raise SystemExit(main())

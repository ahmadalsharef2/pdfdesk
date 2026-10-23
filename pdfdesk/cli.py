"""pdfdesk CLI:  pdfdesk run <Command> in.pdf -o out.pdf [--key value ...]   |   pdfdesk <file.pdf>  (GUI)"""
from __future__ import annotations

import argparse
import json
import sys

import pymupdf

from .commands import COMMANDS, run


def _coerce(v: str):
    try:
        return json.loads(v)
    except ValueError:
        return v


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "run":
        ap = argparse.ArgumentParser(prog="pdfdesk run")
        ap.add_argument("command", choices=sorted(COMMANDS) if COMMANDS else None)
        ap.add_argument("input", nargs="?")
        ap.add_argument("-o", "--output")
        args, rest = ap.parse_known_args(argv[1:])
        kw = {rest[i].lstrip("-").replace("-", "_"): _coerce(rest[i + 1]) for i in range(0, len(rest), 2)}
        doc = pymupdf.open(args.input) if args.input else None
        res = run(args.command, doc, **kw) if doc is not None else run(args.command, **kw)
        out = res if isinstance(res, pymupdf.Document) else doc
        if args.output and out is not None:
            out.save(args.output, garbage=4, deflate=True, clean=True)
        return 0
    if argv and argv[0] == "commands":
        import pdfdesk.commands  # noqa
        print("\n".join(sorted(COMMANDS)))
        return 0
    from .gui.app import launch
    return launch(argv)


if __name__ == "__main__":
    raise SystemExit(main())

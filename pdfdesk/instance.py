"""One window for all launches. A launch sends {"action", "paths"} to the running pdfdesk and exits; the first
launch becomes the window. Explorer starts one process per selected file, so several launches can race: one
wins a lock file and opens the window, the others wait for it to listen and hand their files over.

The client side uses no Qt, so the hand-off happens before PySide6 and PyMuPDF are imported.
"""
from __future__ import annotations

import getpass
import json
import os
import socket
import tempfile
import time

NAME = "pdfdesk-" + "".join(c for c in getpass.getuser() if c.isalnum())


def address() -> str:
    """A Unix socket path on Linux; a named pipe on Windows (QLocalServer adds \\\\.\\pipe\\ itself)."""
    if os.name == "nt":
        return NAME
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(tempfile.gettempdir(), f"pdfdesk-{os.getuid()}")
    return os.path.join(base, "pdfdesk.sock")


def _send(data: bytes) -> bool:
    try:
        if os.name == "nt":
            with open(r"\\.\pipe" + "\\" + NAME, "r+b", buffering=0) as pipe:
                pipe.write(data)
                return pipe.read(2) == b"ok"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(address())
            s.sendall(data)
            return s.recv(2) == b"ok"
    except OSError:
        return False


def hand_off(action: str, paths: list[str], wait: float = 0) -> bool:
    """Give the files to a running pdfdesk; with wait, keep trying that long (it may still be starting)."""
    data = json.dumps({"action": action, "paths": [os.path.abspath(p) for p in paths]}).encode() + b"\n"
    end = time.monotonic() + wait
    while True:
        if _send(data):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)


def become_primary():
    """Try to be the process that shows the window. Returns the held lock, or None if another launch has it.
    QLockFile notices a lock left by a crashed run."""
    from PySide6.QtCore import QLockFile
    lock = QLockFile(os.path.join(tempfile.gettempdir(), NAME + ".lock"))
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(0) else None


def serve(on_message):
    """Listen for later launches; on_message(action, paths) runs in the GUI thread. Returns the server (keep it)."""
    from PySide6.QtNetwork import QLocalServer
    path = address()
    if os.name != "nt":
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    QLocalServer.removeServer(path)          # a stale socket from a crashed run; we hold the lock
    srv = QLocalServer()
    srv.setSocketOptions(QLocalServer.UserAccessOption)
    if not srv.listen(path):
        return None

    def accept():
        while srv.hasPendingConnections():
            c = srv.nextPendingConnection()
            buf = bytearray()

            def read(c=c, buf=buf):
                buf.extend(bytes(c.readAll()))
                if not buf.endswith(b"\n"):           # one JSON line per launch
                    return
                try:
                    msg = json.loads(buf.decode())
                except ValueError:
                    return c.disconnectFromServer()
                c.write(b"ok")
                c.flush()
                c.disconnectFromServer()
                if isinstance(msg, list):             # pdfdesk 0.2.4 and older: a list of files to open
                    msg = {"action": "open", "paths": msg}
                on_message(msg.get("action", "open"), [p for p in msg.get("paths", []) if isinstance(p, str)])

            c.readyRead.connect(read)
    srv.newConnection.connect(accept)
    return srv

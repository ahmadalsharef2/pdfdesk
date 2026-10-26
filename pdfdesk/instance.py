"""One window for all files: a second launch hands its files to the running pdfdesk and exits.

Plain sockets on the client side so the hand-off happens before PySide6 and PyMuPDF are imported.
Linux only; on Windows every launch opens its own window.
"""
from __future__ import annotations

import json
import os
import socket


def sock_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/pdfdesk-{os.getuid()}"
    return os.path.join(base, "pdfdesk.sock")


def hand_off(paths: list[str]) -> bool:
    """Send paths to a running pdfdesk. True if one took them."""
    if os.name == "nt":
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock_path())
            s.sendall(json.dumps([os.path.abspath(p) for p in paths]).encode() + b"\n")
            return s.recv(2) == b"ok"
    except OSError:
        return False


def serve(on_paths):
    """Listen for later launches; on_paths(list[str]) runs in the GUI thread. Returns the server (keep it)."""
    if os.name == "nt":
        return None
    from PySide6.QtNetwork import QLocalServer
    path = sock_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    QLocalServer.removeServer(path)          # a stale socket from a crashed run; hand_off already failed
    srv = QLocalServer()
    srv.setSocketOptions(QLocalServer.UserAccessOption)
    if not srv.listen(path):
        return None

    def accept():
        c = srv.nextPendingConnection()
        buf = bytearray()

        def read():
            buf.extend(bytes(c.readAll()))
            if not buf.endswith(b"\n"):           # one JSON line per launch
                return
            try:
                paths = json.loads(buf.decode())
            except ValueError:
                return c.disconnectFromServer()
            c.write(b"ok")
            c.flush()
            c.disconnectFromServer()
            on_paths(paths)

        c.readyRead.connect(read)
    srv.newConnection.connect(accept)
    return srv

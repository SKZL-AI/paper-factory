"""Minimal CDP (Chrome DevTools Protocol) client for the Paperpal WebView2
pane — stdlib only (socket+json), no dependencies.

Word is started with WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=
--remote-debugging-port=9229, which makes the Office add-in's WebView2
reachable via CDP on localhost. That gives the adapter deterministic,
DOM-level control of the pane (read suggestion lists, click tabs) where
synthetic mouse input fails silently.

Security: localhost-only, read/drive the pane; no credentials touched.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import urllib.request


def _ws_connect(url: str, timeout: float = 10.0) -> socket.socket:
    """ws://host:port/path upgrade handshake; returns the socket."""
    rest = url[len("ws://"):]
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    sock.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("handshake failed")
        resp += chunk
    if b"101" not in resp.split(b"\r\n")[0]:
        raise ConnectionError(f"handshake refused: {resp[:80]!r}")
    return sock


def _send(sock: socket.socket, payload: bytes) -> None:
    mask = os.urandom(4)
    n = len(payload)
    if n < 126:
        head = bytes([0x81, 0x80 | n])
    elif n < 65536:
        head = bytes([0x81, 0x80 | 126]) + n.to_bytes(2, "big")
    else:
        head = bytes([0x81, 0x80 | 127]) + n.to_bytes(8, "big")
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(head + mask + masked)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def _recv_frame(sock: socket.socket) -> bytes:
    """One complete (possibly fragmented) text message; pings answered."""
    payload = b""
    while True:
        h = _recv_exact(sock, 2)
        fin = h[0] & 0x80
        opcode = h[0] & 0x0F
        ln = h[1] & 0x7F
        if ln == 126:
            ln = int.from_bytes(_recv_exact(sock, 2), "big")
        elif ln == 127:
            ln = int.from_bytes(_recv_exact(sock, 8), "big")
        if h[1] & 0x80:
            mask = _recv_exact(sock, 4)
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(_recv_exact(sock, ln)))
        else:
            data = _recv_exact(sock, ln)
        if opcode == 9:  # ping → pong
            pong = bytes([0x8A, 0x80]) + os.urandom(4)
            sock.sendall(pong)
            continue
        if opcode == 0xA:
            continue  # unsolicited pong — not a message (reviewer B R3-F3)
        if opcode == 8:
            raise ConnectionError("closed by peer")
        payload += data
        if fin:
            return payload


class CDP:
    """One CDP session against a page target."""

    def __init__(self, port: int = 9229, target_substring: str = "paperpal"):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json", timeout=10) as r:
            targets = json.loads(r.read().decode())
        pages = [t for t in targets if t.get("type") == "page"]
        hit = [t for t in pages
               if target_substring.lower() in (t.get("url", "") + t.get("title", "")).lower()]
        if not hit:
            raise ConnectionError(
                f"no page target matching {target_substring!r}; "
                f"pages: {[(t.get('title'), t.get('url')) for t in pages]}")
        self._sock = _ws_connect(hit[0]["webSocketDebuggerUrl"])
        self._id = 0
        self.target = {"title": hit[0].get("title"), "url": hit[0].get("url")}

    def call(self, method: str, **params):
        self._id += 1
        _send(self._sock, json.dumps(
            {"id": self._id, "method": method, "params": params}).encode())
        while True:
            msg = json.loads(_recv_frame(self._sock).decode())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def js(self, expr: str):
        r = self.call("Runtime.evaluate", expression=expr,
                      returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

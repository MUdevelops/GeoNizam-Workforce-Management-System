"""
realtime_hub.py
A minimal local pub/sub broker so the Admin dashboard's Live GPS
Tracking screen updates the instant a new location arrives, instead of
waiting for the next poll -- GeoNizam's free, dependency-free
equivalent of a WebSocket/SSE channel, sized for a desktop app where
every process (1 Admin + up to 7 Employee dashboards) runs on the same
machine and already shares one SQLite file.

Design
------
The first process to touch this module binds REALTIME_HUB_PORT on
127.0.0.1 and becomes the broadcast hub; every other process's bind
attempt fails (address already in use) and it becomes a client instead.
Clients send one newline-delimited JSON object per event; the hub
rebroadcasts each line to every other connected client. Nothing here is
persisted -- if the hub isn't reachable, callers still work because the
Admin dashboard keeps a low-frequency SQLite poll as a fallback (see
Admin.py), so a dropped push never makes tracking silently stop.
"""

import json
import socket
import threading

import config

_hub_started = False
_hub_lock = threading.Lock()
_hub_clients = []
_hub_clients_lock = threading.Lock()


def _hub_accept_loop(server_sock):
    while True:
        try:
            conn, _addr = server_sock.accept()
        except OSError:
            return
        with _hub_clients_lock:
            _hub_clients.append(conn)
        threading.Thread(target=_hub_client_reader, args=(conn,), daemon=True).start()


def _hub_client_reader(conn):
    buf = b""
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    _broadcast(line, exclude=conn)
    except OSError:
        pass
    finally:
        with _hub_clients_lock:
            if conn in _hub_clients:
                _hub_clients.remove(conn)
        try:
            conn.close()
        except OSError:
            pass


def _broadcast(line: bytes, exclude=None):
    with _hub_clients_lock:
        targets = [c for c in _hub_clients if c is not exclude]
    for c in targets:
        try:
            c.sendall(line + b"\n")
        except OSError:
            pass


def ensure_hub_started():
    """Idempotently tries to become the hub for this machine. Safe to
    call from every process -- exactly one of them will succeed."""
    global _hub_started
    with _hub_lock:
        if _hub_started:
            return
        try:
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind((config.REALTIME_HUB_HOST, config.REALTIME_HUB_PORT))
            server_sock.listen(16)
            threading.Thread(target=_hub_accept_loop, args=(server_sock,), daemon=True).start()
            _hub_started = True
        except OSError:
            # Another process on this machine is already the hub -- fine,
            # this process will just act as a client via publish()/Subscriber.
            pass


def publish(event: dict):
    """Fire-and-forget: sends one JSON event to the hub. Never raises --
    if the hub is unreachable the event is simply dropped, and the
    Admin dashboard's polling fallback will pick up the change instead."""
    ensure_hub_started()
    try:
        with socket.create_connection(
            (config.REALTIME_HUB_HOST, config.REALTIME_HUB_PORT), timeout=1.0
        ) as s:
            s.sendall((json.dumps(event) + "\n").encode("utf-8"))
    except OSError:
        pass


class Subscriber:
    """Persistent connection that invokes `callback(event_dict)` for every
    event published by any process, on a background thread. The caller
    (Admin.py) is responsible for marshalling the callback back onto the
    Tkinter main thread (e.g. via `self.after(0, ...)`)."""

    def __init__(self, callback):
        self._callback = callback
        self._stop = threading.Event()
        self._sock = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        ensure_hub_started()
        while not self._stop.is_set():
            try:
                self._sock = socket.create_connection(
                    (config.REALTIME_HUB_HOST, config.REALTIME_HUB_PORT), timeout=2.0
                )
                self._sock.settimeout(1.0)
                buf = b""
                while not self._stop.is_set():
                    try:
                        chunk = self._sock.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line.decode("utf-8"))
                        except Exception:
                            continue
                        self._callback(event)
            except OSError:
                pass
            finally:
                if self._sock is not None:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
            if not self._stop.is_set():
                self._stop.wait(2.0)  # brief backoff before reconnecting

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

"""Socket writer restricted to loopback fake-controller tests.

There is intentionally no real/private-host scope. Production gateway uses
CommandClient, whose API accepts ReadCommand only.
"""

from __future__ import annotations

import socket
from threading import Lock

from .adapter import read_waypoint_id
from .command_codec import CommandFrameDecoder, decode_reply, encode_read
from .models import ProtocolError, ReadCommand, ResponseUnknown
from .motion_codec import LinearWaypoint, decode_write_reply, encode_software_stop


class FakeMotionClient:
    def __init__(self, host: str, port: int, *, timeout_s: float = 0.5) -> None:
        if host != "127.0.0.1" or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("fake motion client is loopback-only")
        if not 0 < timeout_s <= 5:
            raise ValueError("invalid fake motion timeout")
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self._socket: socket.socket | None = None
        self._decoder = CommandFrameDecoder()
        self._lock = Lock()

    def connect(self) -> None:
        with self._lock:
            if self._socket is not None:
                raise RuntimeError("already connected")
            self._socket = socket.create_connection((self.host, self.port), self.timeout_s)
            self._socket.settimeout(self.timeout_s)
        try:
            marker = self._exchange(b"FakeOnlyIdentity,;")
            if marker != b"FakeOnlyIdentity,OK,INTERN-S2-FAKE-MOTION-V1,;":
                raise ValueError("peer did not prove it is the motion-enabled fake controller")
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                self._socket.close()
            self._socket = None
            self._decoder = CommandFrameDecoder()

    def _exchange(self, frame: bytes) -> bytes:
        if not self._lock.acquire(timeout=self.timeout_s):
            raise ResponseUnknown("fake command socket busy; write not delivered")
        try:
            if self._socket is None:
                raise RuntimeError("fake command socket is disconnected")
            if self._decoder.pending:
                self._socket.close()
                self._socket = None
                raise ProtocolError("unexpected buffered fake reply")
            try:
                self._socket.sendall(frame)
                while True:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        raise ResponseUnknown("fake controller closed before reply")
                    replies = self._decoder.feed(chunk)
                    if len(replies) > 1 or (replies and self._decoder.pending):
                        raise ProtocolError("unsolicited fake reply")
                    if replies:
                        return replies[0]
            except (OSError, ResponseUnknown) as exc:
                self._socket.close()
                self._socket = None
                raise ResponseUnknown("fake write outcome unknown; do not retry") from exc
            except ProtocolError:
                self._socket.close()
                self._socket = None
                raise
        finally:
            self._lock.release()

    def waypoint(self, waypoint: LinearWaypoint) -> bool:
        return decode_write_reply(self._exchange(waypoint.encode()), command="WayPoint")

    def software_stop(self) -> bool:
        return decode_write_reply(self._exchange(encode_software_stop()), command="GrpStop")

    def current_waypoint_id(self) -> str:
        frame = self._exchange(encode_read(ReadCommand.CURRENT_WAYPOINT_ID))
        return read_waypoint_id(decode_reply(frame, expected=ReadCommand.CURRENT_WAYPOINT_ID))

    def __enter__(self) -> "FakeMotionClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

"""One-in-flight read-only TCP client; real access requires an explicit scope."""

from __future__ import annotations

import ipaddress
import math
import socket
import threading
from typing import Literal

from .adapter import read_fast_port
from .command_codec import CommandFrameDecoder, decode_reply, encode_read
from .models import CommandReply, FAST_PORT_COMMANDS, ProtocolError, ReadCommand, ResponseUnknown


def _loopback_host(host: str) -> str:
    if host == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("Step 4 accepts literal loopback addresses only") from exc
    if not address.is_loopback:
        raise ValueError("Step 4 cannot connect to a real controller")
    return str(address)


_CONTROLLER_SUBNETS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


def _private_controller_host(host: str) -> str:
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError as exc:
        raise ValueError("real controller host must be a literal private IPv4 address") from exc
    if not any(address in subnet for subnet in _CONTROLLER_SUBNETS):
        raise ValueError("real controller host must be a private IPv4 address")
    return str(address)


def _validated_host(host: str, scope: Literal["loopback", "private-read-only"]) -> str:
    if scope == "loopback":
        return _loopback_host(host)
    if scope == "private-read-only":
        return _private_controller_host(host)
    raise ValueError("unsupported controller connection scope")


class CommandClient:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout_s: float = 2.0,
        fast_port: bool = False,
        scope: Literal["loopback", "private-read-only"] = "loopback",
    ) -> None:
        self.host = _validated_host(host, scope)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port is out of range")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        self.port = port
        self.timeout_s = timeout_s
        self.fast_port = fast_port
        self.scope = scope
        self._socket: socket.socket | None = None
        self._decoder = CommandFrameDecoder()
        self._lock = threading.Lock()

    def connect(self) -> None:
        with self._lock:
            if self._socket is not None:
                raise RuntimeError("already connected")
            self._socket = socket.create_connection((self.host, self.port), self.timeout_s)
            self._socket.settimeout(self.timeout_s)
            self._decoder = CommandFrameDecoder()

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._socket is not None:
            self._socket.close()
        self._socket = None
        self._decoder = CommandFrameDecoder()
    # 用 10003向服务器发送命令
    def request(
        self, command: ReadCommand, *, robot_id: int = 0, name: str | None = None,
    ) -> CommandReply:
        frame = encode_read(command, robot_id=robot_id, name=name)
        if self.fast_port and command not in FAST_PORT_COMMANDS:
            raise ValueError("command is not documented for the fast port")
        with self._lock:
            if self._socket is None:
                raise RuntimeError("command socket is not connected")
            if self._decoder.pending:
                self._close_unlocked()
                raise ProtocolError("unexpected bytes before next command")
            try:
                self._socket.sendall(frame)
                while True:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        raise ResponseUnknown("controller closed before reply")
                    replies = self._decoder.feed(chunk)
                    if len(replies) > 1 or (replies and self._decoder.pending):
                        raise ProtocolError("unsolicited or pipelined reply data")
                    if replies:
                        return decode_reply(replies[0], expected=command)
            except (OSError, ResponseUnknown) as exc:
                self._close_unlocked()
                raise ResponseUnknown("reply unknown after command send; do not retry") from exc
            except ProtocolError:
                self._close_unlocked()
                raise

    def discover_fast_port(self) -> int:
        if self.fast_port:
            raise ValueError("fast port must be discovered on ordinary port")
        return read_fast_port(self.request(ReadCommand.FAST_COMMAND_PORT))

    def __enter__(self) -> "CommandClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

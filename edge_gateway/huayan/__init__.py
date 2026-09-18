"""Strict, read-only HansRobot V6 protocol primitives.

Nothing in this package is wired into the real runtime yet. Network clients
accept loopback addresses only until the later on-site commissioning step.
"""

from .models import ProtocolError, ReadCommand, ResponseUnknown

__all__ = ["ProtocolError", "ReadCommand", "ResponseUnknown"]

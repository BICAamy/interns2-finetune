"""Strict, read-only HansRobot V6 protocol primitives.

Network clients default to loopback. Private-controller access is an explicit
Step 6 read-only scope; this package has no motion encoding or sending API.
"""

from .models import ProtocolError, ReadCommand, ResponseUnknown

__all__ = ["ProtocolError", "ReadCommand", "ResponseUnknown"]

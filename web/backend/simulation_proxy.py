"""Backward-compatible names for the provider-neutral robot proxy."""

from .robot_proxy import (
    MJPEGStream,
    RobotObservabilityHTTPClient,
    RobotObserver,
    RobotProxyError,
)

SimulationProxyError = RobotProxyError
SimulationObserver = RobotObserver
RobotSimulationObservabilityHTTPClient = RobotObservabilityHTTPClient

__all__ = (
    "MJPEGStream",
    "SimulationProxyError",
    "SimulationObserver",
    "RobotSimulationObservabilityHTTPClient",
)

"""Compatibility imports for the SOFA robot simulation service."""


def __getattr__(name: str):
    if name == "create_app":
        from .api import create_app

        return create_app
    if name == "SimulationWorker":
        from .simulation_worker import SimulationWorker

        return SimulationWorker
    raise AttributeError(name)

__all__ = ["SimulationWorker", "create_app"]

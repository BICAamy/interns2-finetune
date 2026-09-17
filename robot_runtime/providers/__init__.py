"""Concrete robot runtime providers, loaded only when selected."""


def __getattr__(name: str):
    if name == "HuayanRealStubProvider":
        from .huayan_real import HuayanRealStubProvider

        return HuayanRealStubProvider
    if name == "SimulationProvider":
        from .simulation import SimulationProvider

        return SimulationProvider
    raise AttributeError(name)

__all__ = ["HuayanRealStubProvider", "SimulationProvider"]

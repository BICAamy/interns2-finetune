"""Concrete robot runtime providers, loaded only when selected."""


def __getattr__(name: str):
    if name in {"HuayanRealProvider", "HuayanRealStubProvider"}:
        from .huayan_real import HuayanRealProvider

        return HuayanRealProvider
    if name == "SimulationProvider":
        from .simulation import SimulationProvider

        return SimulationProvider
    raise AttributeError(name)

__all__ = ["HuayanRealProvider", "HuayanRealStubProvider", "SimulationProvider"]

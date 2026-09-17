"""Provider-neutral HTTP boundary for the robot service on port 8001.

Keep package import light so offline config validation needs no web/SOFA stack.
"""


def __getattr__(name: str):
    if name in {"create_app", "create_provider"}:
        from . import api

        return getattr(api, name)
    raise AttributeError(name)

__all__ = ["create_app", "create_provider"]

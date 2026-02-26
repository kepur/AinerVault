"""Database session and engine — import from db.session directly or via this package."""
# Lazy imports: session.py requires ainern2d_shared.config.setting at import time,
# so we expose symbols but defer actual import until first access.

__all__ = ["engine", "SessionLocal", "get_db"]


def __getattr__(name: str):
    if name in __all__:
        from .session import SessionLocal, engine, get_db  # noqa: F811
        _map = {"engine": engine, "SessionLocal": SessionLocal, "get_db": get_db}
        return _map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

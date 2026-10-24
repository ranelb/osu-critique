"""Optional local web frontend.

The package imports cleanly without the ``[web]`` extra; only calling
:func:`create_app` needs FastAPI. Install it with::

    pip install 'osu-critique[web]'
"""
from __future__ import annotations

__all__ = ["create_app"]


def create_app(*args, **kwargs):
    """Build the FastAPI app (raises ImportError when ``[web]`` is missing)."""
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)

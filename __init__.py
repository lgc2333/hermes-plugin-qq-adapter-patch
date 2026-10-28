"""Hermes QQ adapter patch — plugin entry point.

All upstream source lives in the ``qq_adapter_patch`` subpackage: byte-identical
to ``plugins/platforms/qqbot/`` apart from this fork's patches in ``adapter.py``.
This root module only re-exports ``register`` from there. Keeping the plugin
root free of top-level modules (``utils.py``, ``constants.py``, ``crypto.py``,
...) means nothing here can shadow Hermes' own modules when the plugin
directory lands on ``sys.path``.
"""

if __package__:
    from .qq_adapter_patch import register
else:  # imported as a bare top-level module: pytest collection walks up from tests/ and
    # imports this file without the plugin directory on sys.path, so add it here.
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from qq_adapter_patch import register  # noqa: E402

__all__ = ["register"]

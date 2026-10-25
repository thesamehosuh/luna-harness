"""luna_core — shared logic for the Luna harness overlay.

Importable as ``luna_core`` (``luna/lib`` is added to ``sys.path`` by the test conftest and by the
deploy install). Every Luna plugin depends on this package; it must not import upstream hermes at
module load time (upstream imports are lazy, inside functions, so unit tests run without the full
hermes environment).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0a1"

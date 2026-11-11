"""Remote Mic - RC003 Windows client (source/build candidate).

See this package's README.md for supported capabilities and setup steps.
"""

from pathlib import Path

__all__ = ["__version__"]

__version__ = Path(__file__).with_name("VERSION").read_text(encoding="ascii").strip()
if not __version__:
    raise RuntimeError("RC003 VERSION file is empty")

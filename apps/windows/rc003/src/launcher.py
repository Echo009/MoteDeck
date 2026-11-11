"""Standalone PyInstaller entry point (XRBM-021 In-scope item 1).

PyInstaller's ``Analysis()`` executes its entry script as a top-level
module with NO parent package, regardless of where that script lives on
disk or what package it is a sibling of - see the red baseline recorded in
the XRBM-021 task book. Analyzing ``motedeck/__main__.py`` directly was
therefore always broken for a frozen build: that file legitimately uses
package-relative imports (``from . import ...``, correct for its OTHER
entry point, ``python -m motedeck``), and those imports raise
``ImportError: attempted relative import with no known parent package`` the
moment the frozen executable actually runs - even though the PyInstaller
*build* itself completes without error, since static analysis never
executes the script.

This launcher is intentionally NOT part of the ``motedeck`` package (it
lives outside ``src/motedeck/``, as a sibling of it under ``src/``) and
contains nothing but a single absolute import plus a call - it never has a
parent package either, but an ABSOLUTE import does not need one.
build/MoteDeck.spec's ``Analysis()`` now points here instead of
at the package's own ``__main__.py``, which keeps every module inside the
package on ordinary package-relative imports (unchanged, including
``__main__.py`` itself) while giving PyInstaller a true top-level script
that can actually run once frozen.
"""

from __future__ import annotations

from motedeck.__main__ import main

if __name__ == "__main__":
    main()

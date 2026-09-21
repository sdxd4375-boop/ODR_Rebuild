"""Windows-friendly dev launcher; thin wrapper around ``python -m server``.

Kept because it is the documented shortcut in the README. The event loop
handling lives in src/server/__main__.py — see that module for the why.

Usage: uv run python scripts/dev_server.py
"""

from server.__main__ import main

if __name__ == "__main__":
    main()
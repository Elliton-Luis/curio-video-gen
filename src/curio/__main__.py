"""Permite `python3 -m curio ...` sem instalação."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

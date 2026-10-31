"""Allows `python -m cedt prog.c`."""
import sys

from .cli import main

sys.exit(main())

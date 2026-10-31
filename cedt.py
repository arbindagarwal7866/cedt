#!/usr/bin/env python3
"""CEDT launcher:  python cedt.py prog.c   (see python cedt.py --help)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cedt.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

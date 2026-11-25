#!/usr/bin/env python3
"""Start Recompiler Gundam Breaker 3 Break Edition from this folder (python3 app/main.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gb3r.__main__ import cli  # noqa: E402

sys.exit(cli(sys.argv[1:]))

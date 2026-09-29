#!/usr/bin/env python3
"""Launcher: `./kalebridge.py <command>` or symlink it as /usr/local/bin/kalebridge."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from kalebridge.cli import main  # noqa: E402

sys.exit(main())

"""Shared pytest configuration — adds scripts/ to sys.path."""

import sys
from pathlib import Path

# Make scripts/ importable without installing the package.
# Must happen before any test file imports from scripts/.
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

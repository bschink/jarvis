"""Shared pytest configuration — adds scripts/ and menubar/ to sys.path."""

import sys
from pathlib import Path

# Make scripts/ and menubar/ importable without installing the packages.
# Must happen before any test file imports from these directories.
_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "menubar"))

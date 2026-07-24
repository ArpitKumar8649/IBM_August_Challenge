"""Pytest configuration — make the repo root importable so `import engine...` works."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

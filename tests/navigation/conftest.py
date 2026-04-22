"""
Pytest configuration for tests/navigation/.
Adds the navigation package directory to sys.path so test files can use
direct imports: `from engine import ...`, `from fixtures.trace_generators import ...`
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

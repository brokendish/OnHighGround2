"""
Pytest configuration for tests/navigation/.

- Adds the navigation package directory to sys.path for direct imports.
- Provides session-scoped result stores for the parameter sweep tests.
- Generates markdown reports in reports/parameter_sweep/ at session end.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest


# ── Session-scoped result stores ─────────────────────────────────────────────
# Each list accumulates dicts appended by the sweep test functions.
# They are cleared at session start and read by pytest_sessionfinish.

_arrival_results     = []
_reroute_results     = []
_interaction_results = []


@pytest.fixture(scope="session")
def arrival_results():
    return _arrival_results


@pytest.fixture(scope="session")
def reroute_results():
    return _reroute_results


@pytest.fixture(scope="session")
def interaction_results():
    return _interaction_results


# ── Report generation ─────────────────────────────────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    """Generate markdown reports after all tests have run."""
    # Only generate if any results were collected
    if not (_arrival_results or _reroute_results or _interaction_results):
        return
    try:
        from report_generator import generate_all_reports
        generate_all_reports(_arrival_results, _reroute_results, _interaction_results)
    except Exception as exc:
        # Report generation failure must not hide test failures
        print(f'\n  [sweep] WARNING: report generation failed: {exc}')

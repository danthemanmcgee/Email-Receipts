"""
tests/conftest.py – pytest configuration for the test suite.

Integration tests (marked with @pytest.mark.integration) require live Google
credentials.  They are automatically skipped when the environment variables
GOOGLE_OAUTH_CLIENT_ID or GOOGLE_OAUTH_CLIENT_SECRET are absent, allowing the
full test suite to run in CI without any secrets configured.

To opt in to integration tests locally, export the required variables and run:

    pytest -m integration

See README.md – "Running Tests" for full details.
"""
import os

import pytest


# ---------------------------------------------------------------------------
# Automatic skip for integration tests without Google credentials
# ---------------------------------------------------------------------------

def _has_google_creds() -> bool:
    """Return True when the minimum Google OAuth credentials are present."""
    return bool(
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    )


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.integration tests when Google credentials are absent."""
    if _has_google_creds():
        # Credentials present – let the test runner decide what to execute.
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "Integration test skipped: GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET are not set. "
            "Export those variables and run 'pytest -m integration' to opt in."
        )
    )
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# Convenience fixture: explicitly request a skip inside a test body
# ---------------------------------------------------------------------------

@pytest.fixture
def skip_if_no_google_creds():
    """Fixture that skips the test when Google credentials are not configured.

    Usage::

        def test_something_live(skip_if_no_google_creds):
            # This body only runs when GOOGLE_OAUTH_CLIENT_ID and
            # GOOGLE_OAUTH_CLIENT_SECRET are set.
            ...
    """
    if not _has_google_creds():
        pytest.skip(
            "Skipping: GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET not set."
        )

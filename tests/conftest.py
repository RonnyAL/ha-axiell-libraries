"""Home Assistant fixtures for offline integration lifecycle tests."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow loading this custom integration in HA's real flow manager."""

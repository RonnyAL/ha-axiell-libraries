"""Real HA options flows preserve account identity and validate polling cadence."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant.common import MockConfigEntry

from custom_components.axiell_libraries.const import DOMAIN
from tests.test_config_flow import entry_data


@pytest.mark.parametrize(
    ("options", "minutes"), [({}, 360), ({"update_interval": 720}, 720)]
)
async def test_options_form_defaults_to_existing_or_six_hour_interval(
    hass, options, minutes
):
    """Missing options must retain the old polling cadence without a migration."""
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data(), options=options)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["data_schema"]({}) == {"update_interval": minutes}
    assert dict(entry.options) == options


@pytest.mark.parametrize("minutes", [30, 360, 1440])
async def test_options_persist_inclusive_bounds_without_changing_account(hass, minutes):
    """An options change must preserve stored identity and avoid login or reload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=entry_data(),
        options={"existing_option": "preserved"},
        unique_id="synthetic-account",
    )
    entry.add_to_hass(hass)
    with (
        patch("secrets.token_hex") as token_hex,
        patch(
            "custom_components.axiell_libraries.solus.SolusClient.async_login"
        ) as login,
        patch.object(hass.config_entries, "async_reload") as reload,
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"update_interval": minutes}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "existing_option": "preserved",
        "update_interval": minutes,
    }
    assert type(entry.options["update_interval"]) is int
    assert dict(entry.data) == entry_data()
    assert entry.unique_id == "synthetic-account"
    token_hex.assert_not_called()
    login.assert_not_called()
    reload.assert_not_called()


@pytest.mark.parametrize("minutes", [29, 1441, -30, 30.5, "360", True, None])
async def test_options_reject_invalid_interval_without_persisting(hass, minutes):
    """Invalid types and intervals must never replace a saved polling cadence."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=entry_data(), options={"update_interval": 720}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"update_interval": minutes}
        )

    assert dict(entry.options) == {"update_interval": 720}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"update_interval": 60}


@pytest.mark.parametrize("language", ["en", "nb"])
async def test_options_and_freshness_translations_are_available_to_ha(hass, language):
    """The native form and each diagnostic state must have localized labels."""
    options = await async_get_translations(hass, language, "options", {DOMAIN})
    entity = await async_get_translations(hass, language, "entity", {DOMAIN})

    assert options[f"component.{DOMAIN}.options.step.init.data.update_interval"]
    assert entity[f"component.{DOMAIN}.entity.sensor.data_freshness.name"]
    assert entity[f"component.{DOMAIN}.entity.sensor.last_successful_refresh.name"]
    assert entity[f"component.{DOMAIN}.entity.button.refresh.name"] == (
        "Oppdater nå" if language == "nb" else "Refresh now"
    )
    for state in ("fresh", "stale", "unavailable"):
        assert entity[f"component.{DOMAIN}.entity.sensor.data_freshness.state.{state}"]

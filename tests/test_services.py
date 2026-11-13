"""Offline HA action calls using real account coordinators and consent managers."""

from unittest.mock import patch

import probatio
import pytest
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from pytest_homeassistant.common import MockConfigEntry

from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.solus import RenewalReply, SolusConnectionError
from tests.test_entities import CARD, DEVICE, PIN, entry, setup
from tests.test_entities import api as api


async def call(hass, config, *, response=True, **data):
    return await hass.services.async_call(
        DOMAIN,
        "renew_loan",
        {"config_entry_id": config.entry_id, "loan_id": "loan-a", **data},
        blocking=True,
        return_response=response,
    )


async def test_registered_action_renews_selected_account_and_publishes(hass, api):
    api.rows[0]["canRenew"] = True
    first = entry(hass)
    ids = await setup(hass, first)
    second = entry(hass, "1")
    await setup(hass, second)
    assert (
        hass.services.supports_response(DOMAIN, "renew_loan")
        is SupportsResponse.OPTIONAL
    )
    writes = []

    async def write(client, user_id, loan_id, source, **kwargs):
        writes.append((client._device_id, user_id, loan_id, source))
        api.rows[0]["dueObject"] = "/Date(1795651200000)/"
        return RenewalReply("success", "Renewed")

    with patch(
        "custom_components.axiell_libraries.solus.SolusClient.async_renew_loan", write
    ):
        result = await call(hass, second)
        assert result == {
            "status": "renewed",
            "loan_id": "loan-a",
            "message": "Renewed",
            "refreshed": True,
        }
        assert writes == [("fedcba9876543210", "TEST-CARD-0001", "loan-a", "ILS")]
        assert (
            hass.states.get(ids["active_loans"]).attributes["loans"][0]["due_date"]
            == "2026-11-19"
        )
        assert await call(hass, first, response=False) is None
    assert writes[-1] == (DEVICE, CARD, "loan-a", "ILS")


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"config_entry_id": ""},
        {"config_entry_id": None},
        {"config_entry_id": "   "},
        {"config_entry_id": "unused", "loan_id": ""},
        {"config_entry_id": "unused", "loan_id": "loan-a", "Source": "other"},
        {"config_entry_id": "unused", "loan_id": "loan-a", "PromptAcknowledged": "fee"},
    ],
)
async def test_required_account_and_schema_reject_before_io(hass, api, data):
    await setup(hass, entry(hass))
    assert hass.services.has_service(DOMAIN, "renew_loan")
    with pytest.raises((probatio.Invalid, ServiceValidationError)):
        await hass.services.async_call(DOMAIN, "renew_loan", data, blocking=True)


@pytest.mark.parametrize(
    "kind,key",
    [
        ("missing", "service_config_entry_not_found"),
        ("wrong_domain", "service_config_entry_wrong_domain"),
        ("unloaded", "service_config_entry_not_loaded"),
    ],
)
async def test_invalid_account_uses_core_validation(hass, api, kind, key):
    config = entry(hass)
    await setup(hass, config)
    coordinator = config.runtime_data
    if kind == "wrong_domain":
        invalid = MockConfigEntry(domain="other", title="Other", data={})
        invalid.add_to_hass(hass)
        selected = invalid.entry_id
    elif kind == "unloaded":
        await hass.config_entries.async_unload(config.entry_id)
        selected = config.entry_id
    else:
        selected = "nonexistent"
    with patch.object(
        coordinator, "async_renew_loan", side_effect=AssertionError("I/O")
    ):
        with pytest.raises(ServiceValidationError) as exc:
            await call(hass, config, config_entry_id=selected)
    assert exc.value.translation_key == key


async def test_nonadmin_is_denied_before_account_io(hass, api, hass_read_only_user):
    config = entry(hass)
    await setup(hass, config)
    with patch.object(
        config.runtime_data, "async_renew_loan", side_effect=AssertionError("I/O")
    ):
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN,
                "renew_loan",
                {"config_entry_id": config.entry_id, "loan_id": "loan-a"},
                context=Context(user_id=hass_read_only_user.id),
                blocking=True,
            )


@pytest.mark.parametrize(
    "data",
    [
        {"confirm": True},
        {"confirmation_id": "token"},
        {"confirm": False, "confirmation_id": "token"},
        {"confirm": True, "confirmation_id": ""},
    ],
)
async def test_unpaired_confirmation_is_translated_before_io(hass, api, data):
    config = entry(hass)
    await setup(hass, config)
    with patch.object(
        config.runtime_data, "async_renew_loan", side_effect=AssertionError("I/O")
    ):
        with pytest.raises(ServiceValidationError) as exc:
            await call(hass, config, **data)
    assert exc.value.translation_domain == DOMAIN
    assert exc.value.translation_key == "invalid_confirmation"


@pytest.mark.parametrize("response", [True, False])
async def test_fee_consent_is_visible_and_requires_manual_second_call(
    hass, api, response
):
    api.rows[0].update(canRenew=True, renewalCost=2.5)
    config = entry(hass)
    await setup(hass, config)
    writes = []

    async def write(*args, **kwargs):
        writes.append(True)
        return RenewalReply("success", "Renewed")

    with patch(
        "custom_components.axiell_libraries.solus.SolusClient.async_renew_loan", write
    ):
        if response:
            result = await call(hass, config)
            assert result["status"] == "confirmation_required"
            token = result["confirmation_id"]
            assert result["expires_in"] == 600
            assert "2.5" in result["message"]
        else:
            with pytest.raises(ServiceValidationError) as exc:
                await call(hass, config, response=False)
            assert exc.value.translation_key == "confirmation_required"
            token = exc.value.translation_placeholders["confirmation_id"]
            assert token in str(exc.value)
            assert "2.5" in str(exc.value)
        assert writes == []
        assert (await call(hass, config, confirm=True, confirmation_id=token))[
            "status"
        ] == "renewed"
        assert writes == [True]


async def test_reload_clears_consent_and_keeps_registration(hass, api):
    api.rows[0].update(canRenew=True, renewalCost=2.5)
    config = entry(hass)
    await setup(hass, config)
    token = (await call(hass, config))["confirmation_id"]
    assert await hass.config_entries.async_reload(config.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as exc:
        await call(hass, config, confirm=True, confirmation_id=token)
    assert exc.value.translation_key == "invalid_confirmation"
    assert config.data["device_id"] == DEVICE
    await hass.config_entries.async_unload(config.entry_id)
    assert hass.services.has_service(DOMAIN, "renew_loan")


@pytest.mark.parametrize("response", [True, False])
async def test_known_success_failed_refresh_is_distinct_from_unknown(
    hass, api, response
):
    api.rows[0]["canRenew"] = True
    config = entry(hass)
    await setup(hass, config)

    async def write(*args, **kwargs):
        api.loans_error = SolusConnectionError
        return RenewalReply("success", "Renewed")

    with patch(
        "custom_components.axiell_libraries.solus.SolusClient.async_renew_loan", write
    ):
        if response:
            assert await call(hass, config) == {
                "status": "renewed",
                "loan_id": "loan-a",
                "message": "Renewed",
                "refreshed": False,
            }
        else:
            with pytest.raises(HomeAssistantError) as exc:
                await call(hass, config, response=False)
            assert exc.value.translation_key == "renewed_refresh_failed"
            assert "not" in str(exc.value).lower()
            assert "update" in str(exc.value).lower()


async def test_unknown_outcome_raises_translated_error_without_retry(hass, api):
    api.rows[0]["canRenew"] = True
    config = entry(hass)
    await setup(hass, config)
    writes = []

    async def write(*args, **kwargs):
        writes.append(True)
        raise SolusConnectionError("PRIVATE_PROVIDER_TEXT")

    with patch(
        "custom_components.axiell_libraries.solus.SolusClient.async_renew_loan", write
    ):
        with pytest.raises(HomeAssistantError) as exc:
            await call(hass, config)
    assert exc.value.translation_key == "outcome_unknown"
    assert "PRIVATE_PROVIDER_TEXT" not in str(exc.value)
    assert writes == [True]


@pytest.mark.parametrize(
    "status,key",
    [("error", "provider_rejected"), ("CHARGE-PRIVATE", "confirmation_required")],
)
async def test_provider_text_redacted_through_transport_manager_and_action(
    hass, api, caplog, status, key
):
    api.rows[0]["canRenew"] = True
    config = entry(hass)
    await setup(hass, config)
    client = api.clients[0]
    client._authenticated = True
    client._token = "TEST-AUTH-PRIVATE"
    raw = {
        "d": {
            "status": status,
            "statusmessage": f"<b>Review</b> {CARD} {PIN} {DEVICE} TEST-AUTH-PRIVATE",
        }
    }
    with patch.object(client, "_catalogue_request", return_value=raw):
        with pytest.raises(ServiceValidationError) as exc:
            await call(hass, config, response=False)
    assert exc.value.translation_key == key
    visible = str(exc.value) + str(exc.value.translation_placeholders) + caplog.text
    assert "Review" in visible
    for secret in (CARD, PIN, DEVICE, "TEST-AUTH-PRIVATE", "CHARGE-PRIVATE", "<b>"):
        assert secret not in visible


async def test_admin_can_call_and_action_metadata_selects_integration(
    hass, api, hass_admin_user
):
    from homeassistant.helpers.service import _load_services_file
    from homeassistant.loader import async_get_integration

    api.rows[0]["canRenew"] = True
    config = entry(hass)
    await setup(hass, config)
    integration = await async_get_integration(hass, DOMAIN)
    descriptions = await hass.async_add_executor_job(_load_services_file, integration)
    fields = descriptions["renew_loan"]["fields"]
    assert fields["config_entry_id"]["required"]
    assert fields["config_entry_id"]["selector"] == {
        "config_entry": {"integration": DOMAIN}
    }
    with patch.object(
        api.clients[0],
        "async_renew_loan",
        return_value=RenewalReply("success", "Renewed"),
    ):
        result = await hass.services.async_call(
            DOMAIN,
            "renew_loan",
            {"config_entry_id": config.entry_id, "loan_id": "loan-a"},
            context=Context(user_id=hass_admin_user.id),
            blocking=True,
            return_response=True,
        )
    assert result["status"] == "renewed"


@pytest.mark.parametrize(
    "code,operational",
    [
        ("invalid_confirmation", False),
        ("loan_not_found", False),
        ("not_renewable", False),
        ("missing_source", False),
        ("loan_changed", False),
        ("confirmation_limit", False),
        ("authentication_failed", True),
        ("refresh_failed", True),
        ("entry_closing", True),
    ],
)
async def test_coordinator_error_contract_translates_without_internal_text(
    hass, api, code, operational
):
    from custom_components.axiell_libraries.renewal import RenewalError

    config = entry(hass)
    await setup(hass, config)
    with patch.object(
        config.runtime_data,
        "async_renew_loan",
        side_effect=RenewalError(code, "PRIVATE_INTERNAL_TEXT"),
    ):
        with pytest.raises(HomeAssistantError) as exc:
            await call(hass, config)
    assert exc.value.translation_domain == DOMAIN
    assert exc.value.translation_key == code
    assert isinstance(exc.value, ServiceValidationError) is not operational
    assert "PRIVATE_INTERNAL_TEXT" not in str(exc.value)
    assert not exc.value.translation_placeholders


async def test_action_registered_without_loaded_account(hass):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "renew_loan")
    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            DOMAIN,
            "renew_loan",
            {"config_entry_id": "nonexistent", "loan_id": "loan-a"},
            blocking=True,
        )
    assert exc.value.translation_key == "service_config_entry_not_found"

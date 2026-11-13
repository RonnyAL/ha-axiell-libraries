"""Account authorization through real HA users, policies, registry and actions."""

from unittest.mock import patch

import probatio
import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_READ_ONLY, GROUP_ID_USER
from homeassistant.auth.models import Group
from homeassistant.auth.permissions import PolicyPermissions
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser
from homeassistant.helpers import entity_registry as er

from custom_components.axiell_libraries.const import DOMAIN
from custom_components.axiell_libraries.solus import RenewalReply
from tests.test_entities import CARD, DEVICE, entry, setup
from tests.test_entities import api as api


@pytest.fixture
async def ordinary_user(hass, hass_admin_user):
    """Persist a non-owner user with HA's default Users policy."""
    user = await hass.auth.async_create_user("Household", group_ids=[GROUP_ID_USER])
    assert user.is_active and not user.is_admin and not user.is_owner
    assert isinstance(user.permissions, PolicyPermissions)
    return user


def grant_only(user, entity_id):
    """Replace broad group access with a real HA entity-specific policy."""
    user.groups = [
        Group("Selected account", {"entities": {"entity_ids": {entity_id: True}}})
    ]


async def renew(hass, config, caller_id, *, response=True, **data):
    return await hass.services.async_call(
        DOMAIN,
        "renew_loan",
        {"config_entry_id": config.entry_id, "loan_id": "loan-a", **data},
        context=Context(user_id=caller_id),
        blocking=True,
        return_response=response,
    )


@pytest.mark.parametrize("response", [True, False])
async def test_default_nonadmin_renews_only_selected_account(
    hass, api, ordinary_user, response
):
    """An admin-only wrapper wrongly denies actual Users control permission."""
    api.rows[0]["canRenew"] = True
    first = entry(hass)
    await setup(hass, first)
    second = entry(hass, "1")
    await setup(hass, second)
    writes = []

    async def write(client, card, loan_id, source, **kwargs):
        writes.append((client._device_id, card, loan_id, source))
        return RenewalReply("success", "Renewed")

    with patch(
        "custom_components.axiell_libraries.solus.SolusClient.async_renew_loan", write
    ):
        result = await renew(hass, second, ordinary_user.id, response=response)
    assert result == (
        {
            "status": "renewed",
            "loan_id": "loan-a",
            "message": "Renewed",
            "refreshed": True,
        }
        if response
        else None
    )
    assert writes == [("fedcba9876543210", "TEST-CARD-0001", "loan-a", "ILS")]
    assert first.data["device_id"] == DEVICE
    assert second.data["device_id"] == "fedcba9876543210"


async def test_scoped_control_cannot_renew_other_account_same_loan_id(
    hass, api, ordinary_user
):
    """A domain-wide control check would grant the second account in error."""
    api.rows[0]["canRenew"] = True
    first = entry(hass)
    ids = await setup(hass, first)
    second = entry(hass, "1")
    await setup(hass, second)
    grant_only(ordinary_user, ids["loans"])
    with patch.object(
        api.clients[0],
        "async_renew_loan",
        return_value=RenewalReply("success", "Renewed"),
    ):
        assert (await renew(hass, first, ordinary_user.id))["status"] == "renewed"
    with patch.object(
        second.runtime_data,
        "async_renew_loan",
        side_effect=AssertionError("account I/O"),
    ):
        with pytest.raises(Unauthorized):
            await renew(hass, second, ordinary_user.id)


@pytest.mark.parametrize(
    "identity",
    ["read_only", "no_control", "inactive", "inactive_admin", "unknown", "empty"],
)
async def test_invalid_identity_or_control_denies_before_account_and_consent(
    hass, api, ordinary_user, identity
):
    """Invalid identities and read access must never reach account operations."""
    config = entry(hass)
    await setup(hass, config)
    supplied_id = ordinary_user.id
    if identity == "read_only":
        await hass.auth.async_update_user(ordinary_user, group_ids=[GROUP_ID_READ_ONLY])
    elif identity == "no_control":
        await hass.auth.async_update_user(ordinary_user, group_ids=[])
    elif identity in {"inactive", "inactive_admin"}:
        if identity == "inactive_admin":
            await hass.auth.async_update_user(ordinary_user, group_ids=[GROUP_ID_ADMIN])
        await hass.auth.async_deactivate_user(ordinary_user)
    else:
        supplied_id = "missing-user" if identity == "unknown" else ""
    error = UnknownUser if identity in {"unknown", "empty"} else Unauthorized
    with patch.object(
        config.runtime_data,
        "async_renew_loan",
        side_effect=AssertionError("account I/O"),
    ):
        with pytest.raises(error):
            # Malformed consent must not bypass caller authorization.
            await renew(hass, config, supplied_id, confirm=True)


@pytest.mark.parametrize(
    "registry_case", ["missing", "unrelated_platform", "other_entry"]
)
async def test_only_current_matching_registry_entities_grant_access(
    hass, api, ordinary_user, registry_case
):
    """Broad users still need an Axiell entity on the selected account."""
    config = entry(hass)
    await setup(hass, config)
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, config.entry_id):
        registry.async_remove(item.entity_id)
    if registry_case == "unrelated_platform":
        registry.async_get_or_create("sensor", "other", "other", config_entry=config)
    elif registry_case == "other_entry":
        await setup(hass, entry(hass, "1"))
    with patch.object(
        config.runtime_data,
        "async_renew_loan",
        side_effect=AssertionError("account I/O"),
    ):
        with pytest.raises(Unauthorized):
            await renew(hass, config, ordinary_user.id)


async def test_renamed_entity_with_current_control_still_authorizes(
    hass, api, ordinary_user
):
    """Authorization must not depend on default or cached entity names."""
    api.rows[0]["canRenew"] = True
    config = entry(hass)
    ids = await setup(hass, config)
    er.async_get(hass).async_update_entity(
        ids["loans"], new_entity_id="todo.renamed_books"
    )
    await hass.async_block_till_done()
    grant_only(ordinary_user, "todo.renamed_books")
    with patch.object(
        api.clients[0],
        "async_renew_loan",
        return_value=RenewalReply("success", "Renewed"),
    ):
        assert (await renew(hass, config, ordinary_user.id))["status"] == "renewed"


@pytest.mark.parametrize("response", [True, False])
async def test_revoked_control_denies_confirmation_without_consuming_token(
    hass, api, ordinary_user, response
):
    """A cached decision would allow renewal after control was revoked."""
    api.rows[0].update(canRenew=True, renewalCost=2.5)
    config = entry(hass)
    await setup(hass, config)
    if response:
        token = (await renew(hass, config, ordinary_user.id))["confirmation_id"]
    else:
        with pytest.raises(ServiceValidationError) as exc:
            await renew(hass, config, ordinary_user.id, response=False)
        assert exc.value.translation_key == "confirmation_required"
        token = exc.value.translation_placeholders["confirmation_id"]
    await hass.auth.async_update_user(ordinary_user, group_ids=[GROUP_ID_READ_ONLY])
    with patch.object(
        config.runtime_data,
        "async_renew_loan",
        side_effect=AssertionError("account I/O"),
    ):
        with pytest.raises(Unauthorized):
            await renew(
                hass, config, ordinary_user.id, confirm=True, confirmation_id=token
            )
    await hass.auth.async_update_user(ordinary_user, group_ids=[GROUP_ID_USER])
    with patch.object(
        api.clients[0],
        "async_renew_loan",
        return_value=RenewalReply("success", "Renewed"),
    ):
        assert (
            await renew(
                hass, config, ordinary_user.id, confirm=True, confirmation_id=token
            )
        )["status"] == "renewed"


async def test_denied_caller_cannot_consume_permitted_callers_provider_token(
    hass, api, ordinary_user, hass_read_only_user
):
    """Denied confirmation must preserve exact provider consent for its caller."""
    api.rows[0]["canRenew"] = True
    config = entry(hass)
    await setup(hass, config)
    acknowledgements = []

    async def write(
        client, card, loan_id, source, *, acknowledged_codes=(), sensitive_values=()
    ):
        assert (client._device_id, card, loan_id, source) == (
            DEVICE,
            CARD,
            "loan-a",
            "ILS",
        )
        acknowledgements.append(acknowledged_codes)
        if not acknowledged_codes:
            return RenewalReply(
                "confirmation_required", "Review library fee", "FEE-SYNTHETIC"
            )
        return RenewalReply("success", "Renewed")

    with patch(
        "custom_components.axiell_libraries.solus.SolusClient.async_renew_loan", write
    ):
        prompt = await renew(hass, config, ordinary_user.id)
        assert prompt["status"] == "confirmation_required"
        assert prompt["message"] == "Review library fee"
        token = prompt["confirmation_id"]
        with patch.object(
            config.runtime_data,
            "async_renew_loan",
            side_effect=AssertionError("account I/O"),
        ):
            with pytest.raises(Unauthorized):
                await renew(
                    hass,
                    config,
                    hass_read_only_user.id,
                    confirm=True,
                    confirmation_id=token,
                )
        assert (
            await renew(
                hass, config, ordinary_user.id, confirm=True, confirmation_id=token
            )
        )["status"] == "renewed"
    assert acknowledgements == [(), ("FEE-SYNTHETIC",)]


async def test_owner_policy_authorizes(hass, api, hass_admin_user):
    """Owners continue to succeed through HA's real owner policy."""
    api.rows[0]["canRenew"] = True
    config = entry(hass)
    await setup(hass, config)
    # The harness admin is not an owner; use the real model owner policy.
    hass_admin_user.is_owner = True
    owner = hass_admin_user
    with patch.object(
        api.clients[0],
        "async_renew_loan",
        return_value=RenewalReply("success", "Renewed"),
    ):
        assert (await renew(hass, config, owner.id))["status"] == "renewed"


@pytest.mark.parametrize("field,value", [("user_id", None), ("is_admin", True)])
async def test_caller_cannot_supply_authorization_in_action_data(
    hass, api, field, value
):
    """Schema does not accept a caller's substitute trusted identity or role."""
    config = entry(hass)
    await setup(hass, config)
    with pytest.raises(probatio.Invalid):
        await renew(hass, config, None, **{field: value})

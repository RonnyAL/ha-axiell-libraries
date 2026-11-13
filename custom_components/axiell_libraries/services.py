"""Account-authorized action adapter for explicit, individual loan renewal."""

import probatio
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import service

from .const import DOMAIN
from .renewal import RenewalError

_RENEW_SCHEMA = probatio.Schema(
    {
        probatio.Required("config_entry_id"): probatio.All(
            cv.string, str.strip, probatio.NonEmpty()
        ),
        probatio.Required("loan_id"): probatio.All(
            cv.string, str.strip, probatio.NonEmpty()
        ),
        probatio.Optional("confirm", default=False): bool,
        probatio.Optional("confirmation_id"): cv.string,
    }
)
_OPERATION_ERRORS = {
    "authentication_failed",
    "refresh_failed",
    "outcome_unknown",
    "entry_closing",
}


async def _async_authorize_entry(call: ServiceCall, entry_id: str) -> None:
    """Require current control of an Axiell entity on the selected account."""
    user_id = call.context.user_id
    if user_id is None:
        return
    user = await call.hass.auth.async_get_user(user_id)
    if user is None:
        raise UnknownUser(
            context=call.context, permission=POLICY_CONTROL, user_id=user_id
        )
    if user.is_active:
        registry = er.async_get(call.hass)
        for entity in er.async_entries_for_config_entry(registry, entry_id):
            if entity.platform == DOMAIN and user.permissions.check_entity(
                entity.entity_id, POLICY_CONTROL
            ):
                return
    raise Unauthorized(context=call.context, permission=POLICY_CONTROL, user_id=user_id)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register once at integration setup, independent of entry lifecycle."""

    async def async_renew_loan(call: ServiceCall) -> ServiceResponse:
        await _async_authorize_entry(call, call.data["config_entry_id"])
        entry = service.async_get_config_entry(
            hass, DOMAIN, call.data["config_entry_id"]
        )
        confirm = call.data["confirm"]
        confirmation_id = call.data.get("confirmation_id")
        if (confirmation_id is not None and not confirm) or (
            confirm and not confirmation_id
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_confirmation"
            )
        try:
            result = await entry.runtime_data.async_renew_loan(
                call.data["loan_id"],
                confirm=confirm,
                confirmation_id=confirmation_id,
            )
        except RenewalError as err:
            error_type = (
                HomeAssistantError
                if err.code in _OPERATION_ERRORS
                else ServiceValidationError
            )
            raise error_type(
                translation_domain=DOMAIN,
                translation_key=err.code,
                translation_placeholders=(
                    {"message": err.message}
                    if err.code == "provider_rejected"
                    else None
                ),
            ) from None
        if call.return_response:
            return result.as_dict()
        if result.status == "confirmation_required":
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="confirmation_required",
                translation_placeholders={
                    "message": result.message,
                    "confirmation_id": result.confirmation_id,
                    "expires_in": str(result.expires_in),
                },
            )
        if not result.refreshed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="renewed_refresh_failed",
            )
        return None

    hass.services.async_register(
        DOMAIN,
        "renew_loan",
        async_renew_loan,
        schema=_RENEW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

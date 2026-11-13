"""Administrative action adapter for explicit, individual loan renewal."""

import probatio
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
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


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register once at integration setup, independent of entry lifecycle."""

    async def async_renew_loan(call: ServiceCall) -> ServiceResponse:
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

    service.async_register_admin_service(
        hass,
        DOMAIN,
        "renew_loan",
        async_renew_loan,
        schema=_RENEW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

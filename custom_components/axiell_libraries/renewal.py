"""Explicit per-account renewal transactions and ephemeral consent."""

import json
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from homeassistant.exceptions import ConfigEntryAuthFailed

from .models import Loan
from .solus import SolusError

if TYPE_CHECKING:
    from .coordinator import AxiellCoordinator


@dataclass(frozen=True, slots=True)
class RenewalResult:
    """Small public result, excluding account details and provider codes."""

    status: Literal["renewed", "confirmation_required"]
    loan_id: str
    message: str = field(repr=False)
    refreshed: bool
    confirmation_id: str | None = field(default=None, repr=False)
    expires_in: int | None = None

    def as_dict(self) -> dict[str, str | bool | int]:
        """Return action response fields, omitting absent consent fields."""
        result: dict[str, str | bool | int] = {
            "status": self.status,
            "loan_id": self.loan_id,
            "message": self.message,
            "refreshed": self.refreshed,
        }
        if self.confirmation_id is not None:
            result["confirmation_id"] = self.confirmation_id
        if self.expires_in is not None:
            result["expires_in"] = self.expires_in
        return result


type RenewalErrorCode = Literal[
    "invalid_confirmation",
    "loan_not_found",
    "not_renewable",
    "missing_source",
    "loan_changed",
    "confirmation_limit",
    "authentication_failed",
    "refresh_failed",
    "provider_rejected",
    "outcome_unknown",
    "entry_closing",
]

_MESSAGES: dict[RenewalErrorCode, str] = {
    "invalid_confirmation": "Request new confirmation before renewing this loan.",
    "loan_not_found": "This loan is no longer in the account.",
    "not_renewable": "This loan cannot currently be renewed.",
    "missing_source": "The library did not identify this loan's source.",
    "loan_changed": "The loan changed. Request renewal again to review consent.",
    "confirmation_limit": "The library returned repeated or too many consent prompts.",
    "authentication_failed": "Authentication failed. Reauthenticate this account.",
    "refresh_failed": "Unable to read current loans. No renewal was attempted.",
    "provider_rejected": "The library rejected renewal.",
    "outcome_unknown": "Renewal outcome is unknown. Check this loan before retrying.",
    "entry_closing": "The library account is unloading. Try again when it is loaded.",
}
_FINGERPRINT_FIELDS = (
    "loanID",
    "itemID",
    "recordID",
    "Source",
    "dueObject",
    "canRenew",
    "RenewalCount",
    "RenewalsRemaining",
    "renewalCost",
    "OverdueSpecified",
    "Overdue",
)
_CONFIRMATION_TTL = 600
_PENDING_LIMIT = 32
_ACKNOWLEDGEMENT_LIMIT = 5


class RenewalError(Exception):
    """Finite public error with safe separate text; exception logging stays static."""

    def __init__(self, code: RenewalErrorCode, message: str | None = None) -> None:
        super().__init__("Library renewal failed")
        self.code = code
        self.message = message or _MESSAGES[code]


@dataclass(frozen=True, slots=True, repr=False)
class _PendingConfirmation:
    token: str
    expires_at: float
    fingerprint: str
    acknowledged_codes: tuple[str, ...]
    challenge: str | None


class RenewalManager:
    """Own one entry's renewal workflow, called under its operation lock."""

    def __init__(self, coordinator: AxiellCoordinator) -> None:
        self._coordinator = coordinator
        self._pending: OrderedDict[str, _PendingConfirmation] = OrderedDict()
        self._circulation: dict[str, str] = {}

    def capture_circulation(self, rows: list[dict]) -> None:
        """Preserve exact original fields privately, including malformed JSON values."""
        self._circulation = {
            row["loanID"].strip(): json.dumps(
                {key: row[key] for key in _FINGERPRINT_FIELDS if key in row},
                sort_keys=True,
                separators=(",", ":"),
            )
            for row in rows
        }

    def clear(self) -> None:
        """Discard memory-only consent when this account shuts down."""
        self._pending.clear()
        self._circulation.clear()

    def _consume(
        self, loan_id: str, confirm: bool, confirmation_id: str | None
    ) -> _PendingConfirmation | None:
        """Validate and consume consent before any network await under the lock."""
        now = time.monotonic()
        for key, pending in tuple(self._pending.items()):
            if pending.expires_at <= now:
                del self._pending[key]
        if (
            type(confirm) is not bool
            or (not confirm and confirmation_id is not None)
            or (
                confirm
                and (not isinstance(confirmation_id, str) or not confirmation_id)
            )
        ):
            raise RenewalError("invalid_confirmation")
        if not confirm:
            return None
        pending = self._pending.get(loan_id)
        if pending is None or pending.token != confirmation_id:
            raise RenewalError("invalid_confirmation")
        del self._pending[loan_id]
        return pending

    def _prompt(
        self,
        loan: Loan,
        message: str,
        acknowledged_codes: tuple[str, ...],
        challenge: str | None = None,
    ) -> RenewalResult:
        token = secrets.token_urlsafe(24)
        self._pending.pop(loan.loan_id, None)
        self._pending[loan.loan_id] = _PendingConfirmation(
            token,
            time.monotonic() + _CONFIRMATION_TTL,
            self._circulation[loan.loan_id],
            acknowledged_codes,
            challenge,
        )
        while len(self._pending) > _PENDING_LIMIT:
            self._pending.popitem(last=False)
        return RenewalResult(
            "confirmation_required",
            loan.loan_id,
            message,
            True,
            token,
            _CONFIRMATION_TTL,
        )

    async def async_renew(
        self, loan_id: str, *, confirm: bool, confirmation_id: str | None
    ) -> RenewalResult:
        coordinator = self._coordinator
        pending = self._consume(loan_id, confirm, confirmation_id)
        if not await coordinator._async_refresh_and_publish_unlocked():
            code = (
                "authentication_failed"
                if isinstance(coordinator.last_exception, ConfigEntryAuthFailed)
                else "refresh_failed"
            )
            raise RenewalError(code)
        loan = next(
            (item for item in coordinator.data.loans if item.loan_id == loan_id), None
        )
        if loan is None:
            self._pending.pop(loan_id, None)
            raise RenewalError("loan_not_found")
        if pending is not None and pending.fingerprint != self._circulation[loan_id]:
            raise RenewalError("loan_changed")
        if not loan.can_renew:
            self._pending.pop(loan_id, None)
            raise RenewalError("not_renewable")
        if not loan.source:
            self._pending.pop(loan_id, None)
            raise RenewalError("missing_source")
        if pending is None and loan.renewal_cost is not None and loan.renewal_cost > 0:
            return self._prompt(
                loan, f"Renewal costs {loan.renewal_cost}. Confirm to continue.", ()
            )
        codes = pending.acknowledged_codes if pending else ()
        if pending is not None and pending.challenge is not None:
            codes = (*codes, pending.challenge)
        # From this point onward, any failure is an uncertain write. This call
        # is deliberately outside the coordinator's read/login recovery loop.
        self._pending.pop(loan_id, None)
        data = coordinator._entry.data
        try:
            reply = await coordinator._client.async_renew_loan(
                data["card"],
                loan_id,
                loan.source,
                acknowledged_codes=codes,
                sensitive_values=(data["card"], data["pin"], data["device_id"]),
            )
        except SolusError:
            await coordinator._async_refresh_and_publish_unlocked()
            raise RenewalError("outcome_unknown") from None
        if reply.outcome == "success":
            refreshed = await coordinator._async_refresh_and_publish_unlocked()
            return RenewalResult("renewed", loan_id, reply.message, refreshed)
        if reply.outcome == "error":
            raise RenewalError("provider_rejected", reply.message)
        challenge = reply.acknowledgement_code
        if (
            challenge is None
            or challenge in codes
            or len(codes) >= _ACKNOWLEDGEMENT_LIMIT
        ):
            raise RenewalError("confirmation_limit")
        return self._prompt(loan, reply.message, codes, challenge)

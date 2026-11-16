"""Per-entry loan refresh with bounded, best-effort catalogue enrichment."""

import asyncio
import logging
import random
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .models import CatalogueRecord, LibrarySnapshot, Loan
from .renewal import RenewalError, RenewalManager, RenewalResult
from .snapshot import SnapshotStore
from .solus import (
    SolusAuthError,
    SolusClient,
    SolusError,
    SolusSecurityError,
    SolusSessionExpired,
)

_LOGGER = logging.getLogger(__name__)
_CATALOGUE_TTL = timedelta(hours=24)
_CACHE_LIMIT = 256
_ENRICHMENT_CONCURRENCY = 4
_RECOVERY_LIMIT = 3
_RECOVERY_BASE_SECONDS = 60

type RecordKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _CachedRecord:
    record: CatalogueRecord
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class _ProviderCooldown:
    expires_at: float
    category: str
    reference: str


class AxiellCoordinator(DataUpdateCoordinator[LibrarySnapshot]):
    """Refresh one library/card using its existing client and persistent identity."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SolusClient,
        *,
        close_session: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        self._snapshots = SnapshotStore(hass, entry)
        self._withheld_category = self._snapshots.withheld
        self._client = client
        self._entry = entry
        self._operation_lock = asyncio.Lock()
        self._renewal = RenewalManager(self)
        self._closing = False
        self._close_session = close_session
        self._shutdown_task: asyncio.Task[None] | None = None
        self._renewal_task: asyncio.Task[RenewalResult] | None = None
        self._cache: OrderedDict[RecordKey, _CachedRecord] = OrderedDict()
        self._needs_login = True
        self._recovery_attempts = 0
        self._recovery_deadline: float | None = None
        self._provider_retry_at = 0.0
        self._last_update_error: str | None = None
        self._error_category: str | None = None
        self._failure_message = "Unable to update library data"
        self._previously_failed = False
        self._catalogue_blocked: SolusError | None = None
        # Retain the provider cooldown across coordinator reconstruction,
        # including explicit reloads. Store only a deadline and safe diagnostics.
        self._cooldowns: dict[str, _ProviderCooldown] = hass.data.setdefault(
            f"{DOMAIN}_cooldowns", {}
        )
        for entry_id, cooldown in tuple(self._cooldowns.items()):
            if cooldown.expires_at <= monotonic():
                self._cooldowns.pop(entry_id)
        if cooldown := self._cooldowns.get(entry.entry_id):
            self._provider_retry_at = cooldown.expires_at
            self._recovery_deadline = cooldown.expires_at
            self._error_category = cooldown.category
            self._last_update_error = cooldown.reference
            self._failure_message = (
                f"Unable to update library data ({cooldown.reference})"
            )

    @property
    def closing(self) -> bool:
        """Whether new entity actions are gated for unload/removal."""
        return self._closing

    def snapshot_identity_matches(self, entry: ConfigEntry) -> bool:
        """Detect account changes without treating PIN/options as a new identity."""
        return self._snapshots.matches_identity(entry)

    async def async_restore_snapshot(self) -> bool:
        """Load coherent history without claiming a successful provider read."""
        restored = await self._snapshots.async_load()
        self._withheld_category = self._snapshots.withheld
        if restored is None:
            return False
        self.data, self._withheld_category = restored
        self.last_update_success = False
        if self._withheld_category:
            self._error_category = self._withheld_category
            self._last_update_error = f"{self._withheld_category}/restored"
        return True

    async def async_remove_snapshot(self) -> None:
        """Drain operations before deleting data; no late save can resurrect it."""
        await self.async_shutdown()
        await _async_drain(asyncio.create_task(self._snapshots.async_remove()))
        self._cooldowns.pop(self._entry.entry_id, None)

    @property
    def last_update_error(self) -> str | None:
        """A finite category/reference; never expose provider exception text."""
        return self._last_update_error

    @property
    def snapshot_available(self) -> bool:
        """A retained snapshot remains usable except after unsafe/account failures."""
        return (
            self.data is not None
            and self._withheld_category is None
            and self._error_category
            not in {
                "credentials",
                "security",
            }
        )

    @property
    def freshness_attributes(self) -> dict:
        """Expose when loans were actually fetched, including during an outage."""
        return {
            "last_successful_refresh": self.data.fetched_at.isoformat()
            if self.data
            else None,
            "data_stale": self.data is not None and not self.last_update_success,
            "last_update_error": self.last_update_error,
        }

    @property
    def data_freshness(self) -> str:
        """Fresh means the last authoritative loan refresh succeeded."""
        if not self.snapshot_available:
            return "unavailable"
        return "fresh" if self.last_update_success else "stale"

    async def async_update_options(self) -> None:
        """Apply polling changes in place, retaining any recovery deadline."""
        self.update_interval = timedelta(
            minutes=self._entry.options.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            )
        )
        if self._listeners and not self._closing:
            self._schedule_refresh()

    @callback
    def _schedule_refresh(self) -> None:
        """Use Core's timer, preserving deadlines across options/manual updates."""
        if self._closing or self._error_category == "credentials":
            return
        if self._recovery_deadline is not None:
            # Core rounds its timer start down to a whole second. Never fire
            # before Retry-After (including when rescheduling an existing timer).
            self._retry_after = max(0, self._recovery_deadline - monotonic()) + 1
        super()._schedule_refresh()

    @callback
    def _async_refresh_finished(self) -> None:
        """Core suppresses callbacks on consecutive failures; diagnostics can change."""
        if self._previously_failed and not self.last_update_success:
            self.async_update_listeners()

    def _respect_retry_after(self, error: SolusError) -> None:
        if error.retry_after is not None:
            self._provider_retry_at = max(
                self._provider_retry_at, monotonic() + error.retry_after
            )
            self._cooldowns[self._entry.entry_id] = _ProviderCooldown(
                self._provider_retry_at,
                error.category,
                f"{error.category}/{error.reference()}",
            )

    def _failed_refresh(self, error: SolusError) -> UpdateFailed:
        """Select a bounded recovery delay without retrying any request here."""
        self._error_category = error.category
        self._last_update_error = f"{error.category}/{error.reference()}"
        self._failure_message = (
            f"Unable to update library data ({self._last_update_error})"
        )
        self._respect_retry_after(error)
        if self.data is None:
            # A new coordinator is created on each setup retry. A fixed early
            # hint here would reset Core's own exponential setup backoff.
            remaining = self._provider_retry_at - monotonic()
            self._recovery_deadline = self._provider_retry_at if remaining > 0 else None
            return UpdateFailed(
                self._failure_message,
                retry_after=remaining + 1 if remaining > 0 else None,
            )
        delay = self.update_interval.total_seconds()
        if error.retryable and self._recovery_attempts < _RECOVERY_LIMIT:
            base = _RECOVERY_BASE_SECONDS * 2**self._recovery_attempts
            delay = base + random.uniform(0, base / 4)
            self._recovery_attempts += 1
        delay = max(delay, self._provider_retry_at - monotonic())
        self._recovery_deadline = monotonic() + delay
        return UpdateFailed(self._failure_message, retry_after=delay + 1)

    async def async_note_write_failure(self, error: SolusError) -> None:
        """Retain cooldown and unsafe-account policy before reconciliation."""
        if error.retry_after is not None:
            self._failed_refresh(error)
        await self._async_withhold_snapshot(error.category)

    async def _async_withhold_snapshot(self, category: str) -> None:
        """Apply the same drained policy to read and renewal-write failures."""
        if category in {"credentials", "security"}:
            self._withheld_category = category
            await _async_drain(
                asyncio.create_task(
                    self._snapshots.async_mark_withheld(self.data, category)
                )
            )

    async def _async_login(self) -> None:
        """Reuse stored identity; failed recovery stays eligible for a later login."""
        self._needs_login = True
        await self._client.async_login(
            self._entry.data["card"], self._entry.data["pin"]
        )
        self._needs_login = False

    @callback
    def async_set_closing(self, closing: bool) -> None:
        """Gate actions while platforms unload; reopen if platform unload fails."""
        if self._shutdown_task is None:
            self._closing = closing

    async def async_shutdown(self) -> None:
        """Drain active operations before detaching the account session."""
        self._closing = True
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._async_finish_shutdown())
        await _async_drain(self._shutdown_task)

    async def _async_finish_shutdown(self) -> None:
        await super().async_shutdown()
        async with self._operation_lock:
            self._renewal.clear()
            if self._close_session is not None:
                self._close_session()
                self._close_session = None

    async def async_renew_loan(
        self,
        loan_id: str,
        *,
        confirm: bool = False,
        confirmation_id: str | None = None,
    ) -> RenewalResult:
        """Renew one current loan in this account, with explicit consent."""
        if self._closing:
            raise RenewalError("entry_closing")
        async with self._operation_lock:
            if self._closing:
                raise RenewalError("entry_closing")
            self._renewal_task = asyncio.create_task(
                self._renewal.async_renew(
                    loan_id, confirm=confirm, confirmation_id=confirmation_id
                )
            )
            try:
                return await _async_drain(self._renewal_task)
            finally:
                self._renewal_task = None

    async def _async_update_data(self) -> LibrarySnapshot:
        """Serialize polling with account writes and authentication recovery."""
        self._previously_failed = not self.last_update_success
        async with self._operation_lock:
            if self._closing:
                raise UpdateFailed("Library account is unloading")
            return await self._async_refresh_unlocked()

    async def _async_refresh_and_publish_unlocked(self) -> bool:
        """Publish a fresh snapshot without reacquiring the operation lock."""
        try:
            snapshot = await self._async_refresh_unlocked()
        except (ConfigEntryAuthFailed, UpdateFailed) as error:
            previously_failed = not self.last_update_success
            self.async_set_update_error(error)
            if previously_failed:
                self.async_update_listeners()
            if isinstance(error, ConfigEntryAuthFailed):
                self._async_unsub_refresh()
                self._entry.async_start_reauth(self.hass)
            elif self._listeners:
                self._schedule_refresh()
            return False
        self.async_set_updated_data(snapshot)
        return True

    async def _async_refresh_unlocked(self) -> LibrarySnapshot:
        """One read cycle and at most one explicit session-expiry relogin."""
        if (remaining := self._provider_retry_at - monotonic()) > 0:
            raise UpdateFailed(
                self._failure_message, retry_after=remaining + 1
            ) from None
        try:
            if self._needs_login:
                await self._async_login()
            try:
                snapshot = await self._async_fetch_snapshot()
            except SolusSessionExpired as error:
                self._needs_login = True
                if error.retry_after is not None:
                    raise
                await self._async_login()
                snapshot = await self._async_fetch_snapshot()
        except SolusError as error:
            failure = self._failed_refresh(error)
            await self._async_withhold_snapshot(error.category)
            if isinstance(error, SolusSessionExpired):
                self._needs_login = True
            elif isinstance(error, SolusAuthError):
                raise ConfigEntryAuthFailed(self._failure_message) from None
            raise failure from None
        await _async_drain(asyncio.create_task(self._snapshots.async_save(snapshot)))
        self._withheld_category = None
        self._cooldowns.pop(self._entry.entry_id, None)
        self._recovery_attempts = 0
        self._recovery_deadline = None
        self._provider_retry_at = 0.0
        self._retry_after = None
        self._last_update_error = None
        self._error_category = None
        self.last_exception = None
        return snapshot

    async def _async_fetch_snapshot(self) -> LibrarySnapshot:
        rows = await self._client.async_get_loans(self._entry.data["card"])
        loans = tuple(Loan.from_api(row) for row in rows)
        keys = dict.fromkeys(
            (item.record_id, item.source)
            for item in loans
            if item.record_id and item.source
        )
        semaphore = asyncio.Semaphore(_ENRICHMENT_CONCURRENCY)
        self._catalogue_blocked = None
        # Wait for every request before a recovery login changes client auth state.
        results = await asyncio.gather(
            *(self._async_catalogue(key, semaphore) for key in keys),
            return_exceptions=True,
        )
        # Parallel errors may carry different cooldowns. Preserve every hint,
        # even when a security or credential error has diagnostic precedence.
        for result in results:
            if isinstance(result, SolusError):
                self._respect_retry_after(result)
        # Security rejection must never be hidden by optional enrichment.
        for result in results:
            if isinstance(result, SolusSecurityError):
                raise result
        # Credential rejection takes precedence over recoverable session expiry.
        for result in results:
            if isinstance(result, SolusAuthError) and not isinstance(
                result, SolusSessionExpired
            ):
                raise result
        # A rate limit must prevent a relogin prompted by a concurrent expiry.
        for result in results:
            if isinstance(result, SolusError) and (
                result.retry_after is not None or result.status == 429
            ):
                raise result
        for result in results:
            if isinstance(result, BaseException):
                raise result
        records = dict(zip(keys, results, strict=True))
        self._renewal.capture_circulation(rows)
        return LibrarySnapshot(
            loans=tuple(
                item.with_catalogue(metadata)
                if isinstance(
                    metadata := records.get((item.record_id, item.source)),
                    CatalogueRecord,
                )
                else item
                for item in loans
            ),
            fetched_at=datetime.now(UTC),
        )

    async def _async_catalogue(
        self, key: RecordKey, semaphore: asyncio.Semaphore
    ) -> CatalogueRecord | None:
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            if datetime.now(UTC) - cached.fetched_at < _CATALOGUE_TTL:
                return cached.record
        async with semaphore:
            if self._catalogue_blocked is not None:
                raise self._catalogue_blocked
            try:
                payload = await self._client.async_get_record(*key)
            except SolusError as error:
                if (
                    isinstance(error, (SolusAuthError, SolusSecurityError))
                    or error.retry_after is not None
                    or error.status == 429
                ):
                    # Requests already in flight settle; queued requests stop.
                    self._catalogue_blocked = error
                    raise
                return cached.record if cached else None
        if (
            payload is None
            or payload.get("RecordID") != key[0]
            or (payload.get("Source") is not None and payload["Source"] != key[1])
        ):
            return cached.record if cached else None
        record = CatalogueRecord.from_api(payload)
        self._cache[key] = _CachedRecord(record, datetime.now(UTC))
        self._cache.move_to_end(key)
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        return record


async def _async_drain[T](task: asyncio.Task[T]) -> T:
    """Keep ownership across caller cancellations; retrieve any eventual exception."""
    cancelled = False
    while not task.done():
        try:
            # wait() does not propagate caller cancellation to the retained task.
            # Unlike a cancelled shield on Python 3.14, it also does not install
            # a callback that logs a later exception before we retrieve it.
            await asyncio.wait((task,))
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()

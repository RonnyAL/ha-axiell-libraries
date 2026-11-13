"""Per-entry loan refresh with bounded, best-effort catalogue enrichment."""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .models import CatalogueRecord, LibrarySnapshot, Loan
from .renewal import RenewalError, RenewalManager, RenewalResult
from .solus import SolusAuthError, SolusClient, SolusError, SolusSessionExpired

_LOGGER = logging.getLogger(__name__)
_CATALOGUE_TTL = timedelta(hours=24)
_CACHE_LIMIT = 256
_ENRICHMENT_CONCURRENCY = 4

type RecordKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _CachedRecord:
    record: CatalogueRecord
    fetched_at: datetime


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
            update_interval=timedelta(hours=6),
        )
        self._client = client
        self._entry = entry
        self._operation_lock = asyncio.Lock()
        self._renewal = RenewalManager(self)
        self._closing = False
        self._close_session = close_session
        self._shutdown_task: asyncio.Task[None] | None = None
        self._renewal_task: asyncio.Task[RenewalResult] | None = None
        self._cache: OrderedDict[RecordKey, _CachedRecord] = OrderedDict()

    async def _async_login(self) -> None:
        """Reuse stored credentials; no DeviceID or session construction here."""
        try:
            await self._client.async_login(
                self._entry.data["card"], self._entry.data["pin"]
            )
        except SolusAuthError:
            raise ConfigEntryAuthFailed("Library authentication failed") from None
        except SolusError:
            raise UpdateFailed("Unable to update library data") from None

    async def _async_setup(self) -> None:
        """Own initial login for HA's async_config_entry_first_refresh lifecycle."""
        async with self._operation_lock:
            await self._async_login()

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
        async with self._operation_lock:
            if self._closing:
                raise UpdateFailed("Library account is unloading")
            return await self._async_refresh_unlocked()

    async def _async_refresh_and_publish_unlocked(self) -> bool:
        """Publish a fresh snapshot without reacquiring the operation lock."""
        try:
            snapshot = await self._async_refresh_unlocked()
        except ConfigEntryAuthFailed:
            self.async_set_update_error(
                ConfigEntryAuthFailed("Library authentication failed")
            )
            self._entry.async_start_reauth(self.hass)
            return False
        except UpdateFailed:
            self.async_set_update_error(UpdateFailed("Unable to update library data"))
            return False
        self.async_set_updated_data(snapshot)
        return True

    async def _async_refresh_unlocked(self) -> LibrarySnapshot:
        """Retry explicit session expiry once; invalid credentials never retry."""
        for attempt in range(2):
            try:
                return await self._async_fetch_snapshot()
            except SolusSessionExpired:
                if attempt:
                    raise ConfigEntryAuthFailed(
                        "Library authentication failed"
                    ) from None
                await self._async_login()
            except SolusAuthError:
                raise ConfigEntryAuthFailed("Library authentication failed") from None
            except SolusError:
                raise UpdateFailed("Unable to update library data") from None
        raise AssertionError("Unreachable refresh state")

    async def _async_fetch_snapshot(self) -> LibrarySnapshot:
        rows = await self._client.async_get_loans(self._entry.data["card"])
        loans = tuple(Loan.from_api(row) for row in rows)
        keys = dict.fromkeys(
            (item.record_id, item.source)
            for item in loans
            if item.record_id and item.source
        )
        semaphore = asyncio.Semaphore(_ENRICHMENT_CONCURRENCY)
        # Wait for every request before a recovery login changes client auth state.
        results = await asyncio.gather(
            *(self._async_catalogue(key, semaphore) for key in keys),
            return_exceptions=True,
        )
        # Credential rejection takes precedence over recoverable session expiry.
        for result in results:
            if isinstance(result, SolusAuthError) and not isinstance(
                result, SolusSessionExpired
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
            try:
                payload = await self._client.async_get_record(*key)
            except SolusAuthError:
                raise
            except SolusError:
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

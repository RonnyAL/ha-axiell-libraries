"""Per-entry loan refresh with bounded, best-effort catalogue enrichment."""

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .models import CatalogueRecord, LibrarySnapshot, Loan
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
        self, hass: HomeAssistant, entry: ConfigEntry, client: SolusClient
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
        await self._async_login()

    async def _async_update_data(self) -> LibrarySnapshot:
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

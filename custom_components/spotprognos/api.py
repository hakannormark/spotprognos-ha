"""Client for the Spotprognos public JSON API.

Plain Python with aiohttp and no Home Assistant imports, so it can be tested
on its own. Prices are returned exactly as published, in EUR/MWh; converting
them is the caller's job.

Field reference: https://hakannormark.github.io/power-price-oracle/api.html
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

import aiohttp

DEFAULT_BASE_URL = "https://hakannormark.github.io/power-price-oracle/api/v1/"
DEFAULT_TIMEOUT = 30  # seconds


class SpotprognosError(Exception):
    """Base class for errors from the client."""


class SpotprognosConnectionError(SpotprognosError):
    """The file could not be fetched."""


class SpotprognosDataError(SpotprognosError):
    """The file was fetched but is not valid JSON or lacks required fields."""


@dataclass(frozen=True, slots=True)
class Band:
    """A model's price for one hour or month: median and 80 % interval."""

    p50: float
    p10: float | None = None
    p90: float | None = None


@dataclass(frozen=True, slots=True)
class HourPrice:
    """One entry in series[]."""

    start: datetime
    actual: float | None
    source: str
    models: dict[str, Band]


@dataclass(frozen=True, slots=True)
class FxRate:
    """EUR/SEK exchange rate (SEK per EUR)."""

    rate: float
    date: str | None
    source: str | None
    stale: bool


@dataclass(frozen=True, slots=True)
class Forecast:
    """zones/{zone}/forecast.json."""

    zone: str
    zone_name: str | None
    generated_at: datetime
    run_id: str | None
    degraded: bool
    demo: bool
    default_model: str
    models: tuple[str, ...]
    fx: FxRate
    series: tuple[HourPrice, ...]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One entry in models.json."""

    id: str
    name_sv: str
    description_sv: str | None
    is_default: bool


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    """models.json."""

    default_model: str
    models: tuple[ModelInfo, ...]


@dataclass(frozen=True, slots=True)
class LongtermMonth:
    """One calendar month in longterm.json."""

    month: str
    label: str | None
    horizon: int
    models: dict[str, Band]
    market: dict[str, Any] | None
    last_year: float | None


@dataclass(frozen=True, slots=True)
class Longterm:
    """longterm.json."""

    generated_at: datetime | None
    default_model: str
    zones: dict[str, tuple[LongtermMonth, ...]]


class SpotprognosClient:
    """Fetch and parse the Spotprognos JSON files."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client with a shared aiohttp session."""
        self._session = session
        self._base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def async_get_forecast(self, zone: str) -> Forecast:
        """Fetch the hourly forecast for one price zone."""
        return parse_forecast(await self._async_get_json(f"zones/{zone}/forecast.json"))

    async def async_get_models(self) -> ModelCatalog:
        """Fetch the list of available models."""
        return parse_models(await self._async_get_json("models.json"))

    async def async_get_longterm(self) -> Longterm:
        """Fetch the monthly long-term forecast."""
        return parse_longterm(await self._async_get_json("longterm.json"))

    async def _async_get_json(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.get(url, timeout=self._timeout) as resp:
                if resp.status != 200:
                    raise SpotprognosConnectionError(
                        f"{url} returned HTTP {resp.status}"
                    )
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SpotprognosConnectionError(f"Could not fetch {url}: {err!r}") from err

        try:
            data = json.loads(text)
        except ValueError as err:
            raise SpotprognosDataError(f"{url} is not valid JSON: {err}") from err
        if not isinstance(data, dict):
            raise SpotprognosDataError(f"{url} does not contain a JSON object")
        return data


def _number(value: Any) -> float | None:
    """Return value as float if it is a real number, otherwise None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _band(value: Any) -> Band | None:
    """Parse {"p10", "p50", "p90"}; None if p50 is missing."""
    if not isinstance(value, dict):
        return None
    p50 = _number(value.get("p50"))
    if p50 is None:
        return None
    return Band(p50=p50, p10=_number(value.get("p10")), p90=_number(value.get("p90")))


def _bands(value: Any) -> dict[str, Band]:
    if not isinstance(value, dict):
        return {}
    bands = {}
    for model_id, raw in value.items():
        if (band := _band(raw)) is not None:
            bands[model_id] = band
    return bands


def _timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp with offset; None if missing or naive."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SpotprognosDataError(f"Missing or invalid field {key!r}")
    return value


def parse_forecast(data: dict[str, Any]) -> Forecast:
    """Parse zones/{zone}/forecast.json. Unknown fields are ignored."""
    generated_at = _timestamp(data.get("generated_at"))
    if generated_at is None:
        raise SpotprognosDataError("Missing or invalid field 'generated_at'")

    fx_raw = data.get("fx")
    if not isinstance(fx_raw, dict):
        raise SpotprognosDataError("Missing field 'fx'")
    rate = _number(fx_raw.get("rate"))
    if rate is None or rate <= 0:
        raise SpotprognosDataError("Missing or invalid field 'fx.rate'")
    fx = FxRate(
        rate=rate,
        date=fx_raw.get("date"),
        source=fx_raw.get("source"),
        stale=bool(fx_raw.get("stale", False)),
    )

    raw_series = data.get("series")
    if not isinstance(raw_series, list):
        raise SpotprognosDataError("Missing field 'series'")
    series: list[HourPrice] = []
    for entry in raw_series:
        if not isinstance(entry, dict):
            continue
        start = _timestamp(entry.get("ts"))
        if start is None:
            continue
        actual = _number(entry.get("actual"))
        source = entry.get("source")
        if not isinstance(source, str):
            source = "official" if actual is not None else "forecast"
        series.append(
            HourPrice(
                start=start,
                actual=actual,
                source=source,
                models=_bands(entry.get("models")),
            )
        )
    if not series:
        raise SpotprognosDataError("Field 'series' contains no usable hours")
    series.sort(key=lambda hour: hour.start)

    models = data.get("models")
    return Forecast(
        zone=_required_str(data, "zone"),
        zone_name=data.get("zone_name"),
        generated_at=generated_at,
        run_id=data.get("run_id"),
        degraded=bool(data.get("degraded", False)),
        demo=bool(data.get("demo", False)),
        default_model=_required_str(data, "default_model"),
        models=tuple(m for m in models if isinstance(m, str))
        if isinstance(models, list)
        else (),
        fx=fx,
        series=tuple(series),
    )


def parse_models(data: dict[str, Any]) -> ModelCatalog:
    """Parse models.json."""
    raw_models = data.get("models")
    if not isinstance(raw_models, list):
        raise SpotprognosDataError("Missing field 'models'")
    models = []
    for raw in raw_models:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            continue
        models.append(
            ModelInfo(
                id=raw["id"],
                name_sv=raw.get("name_sv") or raw["id"],
                description_sv=raw.get("description_sv"),
                is_default=bool(raw.get("is_default", False)),
            )
        )
    return ModelCatalog(
        default_model=_required_str(data, "default_model"), models=tuple(models)
    )


def parse_longterm(data: dict[str, Any]) -> Longterm:
    """Parse longterm.json."""
    raw_zones = data.get("zones")
    if not isinstance(raw_zones, dict):
        raise SpotprognosDataError("Missing field 'zones'")
    zones: dict[str, tuple[LongtermMonth, ...]] = {}
    for zone, raw_zone in raw_zones.items():
        if not isinstance(raw_zone, dict) or not isinstance(
            raw_zone.get("months"), list
        ):
            continue
        months = []
        for raw in raw_zone["months"]:
            if not isinstance(raw, dict):
                continue
            horizon = raw.get("horizon")
            month = raw.get("month")
            if not isinstance(horizon, int) or not isinstance(month, str):
                continue
            raw_models = (
                raw.get("models") if isinstance(raw.get("models"), dict) else {}
            )
            market = raw_models.get("lt_market")
            months.append(
                LongtermMonth(
                    month=month,
                    label=raw.get("label"),
                    horizon=horizon,
                    models=_bands(raw_models),
                    market=market if isinstance(market, dict) else None,
                    last_year=_number(raw.get("last_year")),
                )
            )
        months.sort(key=lambda m: m.horizon)
        zones[zone] = tuple(months)
    return Longterm(
        generated_at=_timestamp(data.get("generated_at")),
        default_model=_required_str(data, "default_model"),
        zones=zones,
    )

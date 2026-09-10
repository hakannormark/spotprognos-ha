"""Data update coordinator for Spotprognos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Forecast, Longterm, LongtermMonth, SpotprognosClient, SpotprognosError
from .const import (
    CONF_MARKUP,
    CONF_MODEL,
    CONF_UNIT,
    CONF_VAT,
    CONF_ZONE,
    DEFAULT_MARKUP,
    DEFAULT_MODEL,
    DEFAULT_UNIT,
    DEFAULT_VAT,
    DOMAIN,
    LOGGER,
    MODEL_FOLLOW_DEFAULT,
    UNIT_ORE_KWH,
    UPDATE_INTERVAL,
    VAT_RATE,
)

# The delivery day is the Swedish calendar day, whatever time zone Home
# Assistant itself runs in.
MARKET_TZ = dt_util.get_time_zone("Europe/Stockholm")

type SpotprognosConfigEntry = ConfigEntry[SpotprognosCoordinator]


@dataclass(frozen=True, slots=True)
class PriceSettings:
    """How raw EUR/MWh prices are presented."""

    unit: str = DEFAULT_UNIT
    markup: float = DEFAULT_MARKUP  # öre/kWh, excluding VAT
    vat: bool = DEFAULT_VAT

    def convert(self, eur_mwh: float | None, fx_rate: float) -> float | None:
        """Convert a spot price to the configured unit, markup and VAT.

        öre/kWh = EUR/MWh × SEK per EUR ÷ 10. Dividing by 10 alone gives
        eurocent, not öre. The markup is added before VAT, so VAT applies to
        both.
        """
        if eur_mwh is None:
            return None
        if self.unit == UNIT_ORE_KWH:
            value = eur_mwh * fx_rate / 10 + self.markup
        else:
            value = eur_mwh + self.markup * 10 / fx_rate
        if self.vat:
            value *= 1 + VAT_RATE
        return round(value, 3)


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One delivery hour, converted to the configured unit."""

    start: datetime
    end: datetime
    value: float | None
    p10: float | None
    p90: float | None
    source: str

    @property
    def official(self) -> bool:
        """Return True if the price is the published day-ahead price."""
        return self.source == "official"


@dataclass(frozen=True, slots=True)
class SpotprognosData:
    """What the entities read."""

    forecast: Forecast
    model: str
    model_fallback: bool
    prices: tuple[PricePoint, ...]
    longterm: Longterm | None

    def price_at(self, when: datetime) -> PricePoint | None:
        """Return the hour that contains the given instant."""
        for point in self.prices:
            if point.start <= when < point.end:
                return point
        return None

    def prices_on(self, day: date) -> list[PricePoint]:
        """Return the hours of one Swedish calendar day."""
        return [point for point in self.prices if point.start.date() == day]

    def next_month(self) -> LongtermMonth | None:
        """Return next month's long-term forecast for this zone."""
        if self.longterm is None:
            return None
        months = self.longterm.zones.get(self.forecast.zone, ())
        return next((m for m in months if m.horizon == 1), None)


def market_today() -> date:
    """Return today's date in the market time zone, from Home Assistant's clock."""
    return dt_util.now(MARKET_TZ).date()


class SpotprognosCoordinator(DataUpdateCoordinator[SpotprognosData]):
    """Fetch forecast.json and longterm.json for one price zone."""

    config_entry: SpotprognosConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SpotprognosConfigEntry) -> None:
        """Initialize the coordinator from a config entry."""
        self.zone: str = entry.data[CONF_ZONE]
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.zone}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = SpotprognosClient(async_get_clientsession(hass))
        options = entry.options
        self.configured_model: str = options.get(CONF_MODEL, DEFAULT_MODEL)
        self.settings = PriceSettings(
            unit=options.get(CONF_UNIT, DEFAULT_UNIT),
            markup=float(options.get(CONF_MARKUP, DEFAULT_MARKUP)),
            vat=bool(options.get(CONF_VAT, DEFAULT_VAT)),
        )
        self._fallback_logged = False
        self._demo_logged = False
        self._degraded_logged = False
        self._longterm_failed = False

    @property
    def fx_rate(self) -> float:
        """Return the exchange rate from the latest forecast."""
        return self.data.forecast.fx.rate

    def convert(self, eur_mwh: float | None) -> float | None:
        """Convert a price with the latest exchange rate."""
        return self.settings.convert(eur_mwh, self.fx_rate)

    @callback
    def async_start_hourly_refresh(self) -> CALLBACK_TYPE:
        """Tell the entities to recompute at the top of every hour.

        The data is fetched every 30 minutes, but the current hour must switch
        exactly on the hour, and today/tomorrow exactly at midnight.
        """
        return async_track_time_change(
            self.hass, self._async_hour_changed, minute=0, second=0
        )

    @callback
    def _async_hour_changed(self, _now: datetime) -> None:
        if self.data is not None:
            self.async_update_listeners()

    async def _async_update_data(self) -> SpotprognosData:
        try:
            forecast = await self.client.async_get_forecast(self.zone)
        except SpotprognosError as err:
            raise UpdateFailed(
                f"Could not update Spotprognos {self.zone}: {err}"
            ) from err

        longterm = await self._async_fetch_longterm()
        self._log_flags(forecast)
        model, fallback = self._resolve_model(forecast)

        return SpotprognosData(
            forecast=forecast,
            model=model,
            model_fallback=fallback,
            prices=self._build_prices(forecast, model),
            longterm=longterm,
        )

    async def _async_fetch_longterm(self) -> Longterm | None:
        """Fetch longterm.json; a failure here must not take down the hourly data."""
        try:
            longterm = await self.client.async_get_longterm()
        except SpotprognosError as err:
            if not self._longterm_failed:
                LOGGER.warning(
                    "Could not fetch the Spotprognos long-term forecast, keeping the previous one: %s",
                    err,
                )
                self._longterm_failed = True
            return self.data.longterm if self.data is not None else None
        if self._longterm_failed:
            LOGGER.info("The Spotprognos long-term forecast is available again")
            self._longterm_failed = False
        return longterm

    def _log_flags(self, forecast: Forecast) -> None:
        """Log demo and degraded runs once when they start, not on every poll."""
        if forecast.demo and not self._demo_logged:
            LOGGER.warning(
                "Spotprognos %s is publishing demo data (synthetic prices). "
                "The price sensors are unavailable until real data is back",
                self.zone,
            )
        elif not forecast.demo and self._demo_logged:
            LOGGER.info("Spotprognos %s is publishing real prices again", self.zone)
        self._demo_logged = forecast.demo

        if forecast.degraded and not self._degraded_logged:
            LOGGER.info(
                "Spotprognos run %s for %s is degraded: a source failed and parts "
                "may come from an earlier run",
                forecast.run_id,
                self.zone,
            )
        self._degraded_logged = forecast.degraded

    def _resolve_model(self, forecast: Forecast) -> tuple[str, bool]:
        """Return (model to use, whether that is a fallback)."""
        configured = self.configured_model
        if configured in {MODEL_FOLLOW_DEFAULT, forecast.default_model}:
            return forecast.default_model, False
        if any(configured in hour.models for hour in forecast.series):
            if self._fallback_logged:
                LOGGER.info("Spotprognos model %s is available again", configured)
                self._fallback_logged = False
            return configured, False
        if not self._fallback_logged:
            LOGGER.warning(
                "Spotprognos model %s is missing from the %s forecast, "
                "using the default model %s instead",
                configured,
                self.zone,
                forecast.default_model,
            )
            self._fallback_logged = True
        return forecast.default_model, True

    def _build_prices(self, forecast: Forecast, model: str) -> tuple[PricePoint, ...]:
        rate = forecast.fx.rate
        convert = self.settings.convert
        points = []
        for hour in forecast.series:
            start_utc = hour.start.astimezone(UTC)
            band = hour.models.get(model)
            if hour.actual is not None:
                value, p10, p90 = hour.actual, None, None
            elif band is not None:
                value, p10, p90 = band.p50, band.p10, band.p90
            else:
                # The model has no value for this hour.
                value = p10 = p90 = None
            points.append(
                PricePoint(
                    start=start_utc.astimezone(MARKET_TZ),
                    # Add the hour in UTC so that DST changes come out right.
                    end=(start_utc + timedelta(hours=1)).astimezone(MARKET_TZ),
                    value=convert(value, rate),
                    p10=convert(p10, rate),
                    p90=convert(p90, rate),
                    source=hour.source,
                )
            )
        return tuple(points)

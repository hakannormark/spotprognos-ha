"""Price sensors for Spotprognos."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import (
    MARKET_TZ,
    PricePoint,
    SpotprognosConfigEntry,
    SpotprognosCoordinator,
    SpotprognosData,
)
from .entity import SpotprognosEntity

# Everything comes from the coordinator.
PARALLEL_UPDATES = 0

CHEAPEST_WINDOW_HOURS = 3

# Large lists, excluded from the recorder so the database does not grow by
# a few kilobytes every hour.
LIST_ATTRIBUTES = frozenset(
    {"raw_today", "raw_tomorrow", "today", "tomorrow", "forecast"}
)


def market_day(now: datetime) -> date:
    """Return the Swedish calendar day of an instant."""
    return now.astimezone(MARKET_TZ).date()


def hours_in_day(day: date) -> int:
    """Return 23, 24 or 25, depending on daylight saving time."""
    start = datetime.combine(day, time(), MARKET_TZ).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), MARKET_TZ).astimezone(UTC)
    return round((end - start).total_seconds() / 3600)


def tomorrow_points(data: SpotprognosData, now: datetime) -> list[PricePoint]:
    """Return tomorrow's hours once all of them have official prices.

    The series always holds a forecast for tomorrow, so "data for tomorrow"
    means the published day-ahead prices, as in the Nord Pool integration.
    """
    day = market_day(now) + timedelta(days=1)
    points = data.prices_on(day)
    if len(points) < hours_in_day(day):
        return []
    if not all(point.official and point.value is not None for point in points):
        return []
    return points


def cheapest_window(
    points: list[PricePoint], hours: int = CHEAPEST_WINDOW_HOURS
) -> tuple[PricePoint, PricePoint, float] | None:
    """Return (first hour, last hour, average) of the cheapest consecutive run."""
    best: tuple[PricePoint, PricePoint, float] | None = None
    for i in range(len(points) - hours + 1):
        window = points[i : i + hours]
        values = [point.value for point in window]
        if any(value is None for value in values):
            continue
        if any(a.end != b.start for a, b in pairwise(window)):
            continue
        average = sum(values) / hours  # type: ignore[arg-type]
        if best is None or average < best[2]:
            best = (window[0], window[-1], average)
    return best


def _values(points: list[PricePoint]) -> list[float]:
    return [point.value for point in points if point.value is not None]


def _minimum(points: list[PricePoint]) -> float | None:
    values = _values(points)
    return min(values) if values else None


def _maximum(points: list[PricePoint]) -> float | None:
    values = _values(points)
    return max(values) if values else None


def _average(points: list[PricePoint]) -> float | None:
    values = _values(points)
    return round(sum(values) / len(values), 3) if values else None


def _today(data: SpotprognosData, now: datetime) -> list[PricePoint]:
    return data.prices_on(market_day(now))


def _price_in(hours: int) -> Callable[[SpotprognosData, datetime], float | None]:
    def value(data: SpotprognosData, now: datetime) -> float | None:
        point = data.price_at(now + timedelta(hours=hours))
        return point.value if point else None

    return value


def _point_attributes(
    hours: int,
) -> Callable[[SpotprognosCoordinator, datetime], dict[str, Any]]:
    def attributes(
        coordinator: SpotprognosCoordinator, now: datetime
    ) -> dict[str, Any]:
        data = coordinator.data
        point = data.price_at(now + timedelta(hours=hours))
        return {
            "start": point.start if point else None,
            "source": point.source if point else None,
            "p10": point.p10 if point else None,
            "p90": point.p90 if point else None,
            "model": data.model,
            "fx_rate": data.forecast.fx.rate,
            "fx_stale": data.forecast.fx.stale,
        }

    return attributes


def _cheapest_start(data: SpotprognosData, now: datetime) -> datetime | None:
    window = cheapest_window(_today(data, now))
    return window[0].start if window else None


def _cheapest_attributes(
    coordinator: SpotprognosCoordinator, now: datetime
) -> dict[str, Any]:
    window = cheapest_window(_today(coordinator.data, now))
    return {
        "end": window[1].end if window else None,
        "average": round(window[2], 3) if window else None,
        "unit": coordinator.settings.unit,
        "hours": CHEAPEST_WINDOW_HOURS,
    }


def _raw(point: PricePoint) -> dict[str, Any]:
    return {"start": point.start, "end": point.end, "value": point.value}


def _forecast_attributes(
    coordinator: SpotprognosCoordinator, now: datetime
) -> dict[str, Any]:
    """Nord Pool style lists, plus every coming hour with its interval."""
    data = coordinator.data
    today = _today(data, now)
    tomorrow = tomorrow_points(data, now)
    current = data.price_at(now)
    return {
        "raw_today": [_raw(point) for point in today],
        "raw_tomorrow": [_raw(point) for point in tomorrow],
        "today": [point.value for point in today],
        "tomorrow": [point.value for point in tomorrow],
        "tomorrow_valid": bool(tomorrow),
        "forecast": [
            {
                "start": point.start,
                "end": point.end,
                "value": point.value,
                "p10": point.p10,
                "p90": point.p90,
                "source": point.source,
            }
            for point in data.prices
            if point.end > now
        ],
        "source": current.source if current else None,
        "model": data.model,
        "unit": coordinator.settings.unit,
        "fx_rate": data.forecast.fx.rate,
        "generated_at": data.forecast.generated_at,
    }


@dataclass(frozen=True, kw_only=True)
class SpotprognosSensorEntityDescription(SensorEntityDescription):
    """Describe a Spotprognos sensor."""

    value_fn: Callable[[SpotprognosData, datetime], StateType | datetime]
    attributes_fn: (
        Callable[[SpotprognosCoordinator, datetime], dict[str, Any]] | None
    ) = None
    available_fn: Callable[[SpotprognosData, datetime], bool] | None = None
    is_price: bool = True


SENSORS: tuple[SpotprognosSensorEntityDescription, ...] = (
    SpotprognosSensorEntityDescription(
        key="current_price",
        translation_key="current_price",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_price_in(0),
        attributes_fn=_point_attributes(0),
    ),
    SpotprognosSensorEntityDescription(
        key="next_hour_price",
        translation_key="next_hour_price",
        suggested_display_precision=2,
        value_fn=_price_in(1),
        attributes_fn=_point_attributes(1),
    ),
    SpotprognosSensorEntityDescription(
        key="today_min",
        translation_key="today_min",
        suggested_display_precision=2,
        value_fn=lambda data, now: _minimum(_today(data, now)),
    ),
    SpotprognosSensorEntityDescription(
        key="today_average",
        translation_key="today_average",
        suggested_display_precision=2,
        value_fn=lambda data, now: _average(_today(data, now)),
    ),
    SpotprognosSensorEntityDescription(
        key="today_max",
        translation_key="today_max",
        suggested_display_precision=2,
        value_fn=lambda data, now: _maximum(_today(data, now)),
    ),
    SpotprognosSensorEntityDescription(
        key="tomorrow_min",
        translation_key="tomorrow_min",
        suggested_display_precision=2,
        value_fn=lambda data, now: _minimum(tomorrow_points(data, now)),
        available_fn=lambda data, now: bool(tomorrow_points(data, now)),
    ),
    SpotprognosSensorEntityDescription(
        key="tomorrow_average",
        translation_key="tomorrow_average",
        suggested_display_precision=2,
        value_fn=lambda data, now: _average(tomorrow_points(data, now)),
        available_fn=lambda data, now: bool(tomorrow_points(data, now)),
    ),
    SpotprognosSensorEntityDescription(
        key="tomorrow_max",
        translation_key="tomorrow_max",
        suggested_display_precision=2,
        value_fn=lambda data, now: _maximum(tomorrow_points(data, now)),
        available_fn=lambda data, now: bool(tomorrow_points(data, now)),
    ),
    SpotprognosSensorEntityDescription(
        key="cheapest_3h",
        translation_key="cheapest_3h",
        device_class=SensorDeviceClass.TIMESTAMP,
        is_price=False,
        value_fn=_cheapest_start,
        attributes_fn=_cheapest_attributes,
    ),
)

FORECAST_SENSOR = SpotprognosSensorEntityDescription(
    key="forecast",
    translation_key="forecast",
    suggested_display_precision=2,
    value_fn=_price_in(0),
    attributes_fn=_forecast_attributes,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpotprognosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors for one price zone."""
    coordinator = entry.runtime_data
    entities: list[SpotprognosSensor] = [
        SpotprognosSensor(coordinator, description) for description in SENSORS
    ]
    entities.append(SpotprognosForecastSensor(coordinator, FORECAST_SENSOR))
    async_add_entities(entities)


class SpotprognosSensor(SpotprognosEntity, SensorEntity):
    """A sensor computed from the coordinator's data and Home Assistant's clock."""

    entity_description: SpotprognosSensorEntityDescription

    def __init__(
        self,
        coordinator: SpotprognosCoordinator,
        description: SpotprognosSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.is_price:
            self._attr_native_unit_of_measurement = coordinator.settings.unit

    @property
    def available(self) -> bool:
        """Return whether the sensor has something to show."""
        if not super().available:
            return False
        available_fn = self.entity_description.available_fn
        return available_fn is None or available_fn(
            self.coordinator.data, dt_util.utcnow()
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value for the current hour."""
        return self.entity_description.value_fn(self.coordinator.data, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the attributes for the current hour."""
        attributes_fn = self.entity_description.attributes_fn
        if attributes_fn is None:
            return None
        return attributes_fn(self.coordinator, dt_util.utcnow())


class SpotprognosForecastSensor(SpotprognosSensor):
    """The main sensor: current price with lists for charts and charging planners."""

    _unrecorded_attributes = LIST_ATTRIBUTES

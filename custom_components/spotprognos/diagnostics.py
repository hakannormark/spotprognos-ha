"""Diagnostics for Spotprognos.

Nothing here is secret: the API has no key and the entry holds only the
price zone and display settings, so nothing is redacted.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import SpotprognosConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SpotprognosConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    result: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "last_exception": repr(coordinator.last_exception)
        if coordinator.last_exception
        else None,
        "settings": asdict(coordinator.settings),
        "model": {
            "configured": coordinator.configured_model,
            "used": data.model if data else None,
            "fallback": data.model_fallback if data else None,
        },
        "forecast": None,
        "longterm": None,
    }
    if data is None:
        return result

    forecast = data.forecast
    series = forecast.series
    result["forecast"] = {
        "zone": forecast.zone,
        "generated_at": forecast.generated_at.isoformat(),
        "run_id": forecast.run_id,
        "degraded": forecast.degraded,
        "demo": forecast.demo,
        "default_model": forecast.default_model,
        "models": list(forecast.models),
        "fx": asdict(forecast.fx),
        "hours": len(series),
        "official_hours": sum(1 for hour in series if hour.source == "official"),
        "first_hour": series[0].start.isoformat(),
        "last_hour": series[-1].start.isoformat(),
    }
    if data.longterm is not None:
        month = data.next_month()
        result["longterm"] = {
            "generated_at": data.longterm.generated_at.isoformat()
            if data.longterm.generated_at
            else None,
            "default_model": data.longterm.default_model,
            "next_month": month.month if month else None,
        }
    return result

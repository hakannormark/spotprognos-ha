"""Constants for the Spotprognos integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "spotprognos"
LOGGER = logging.getLogger(__package__)

ATTRIBUTION: Final = "Data från Spotprognos (hakannormark.github.io/power-price-oracle)"

# The files are rewritten four times a day and GitHub Pages caches them for up
# to ten minutes. Polling every 30 minutes is enough; never go below 15.
UPDATE_INTERVAL: Final = timedelta(minutes=30)

ZONES: Final[dict[str, str]] = {
    "SE1": "Luleå",
    "SE2": "Sundsvall",
    "SE3": "Stockholm",
    "SE4": "Malmö",
}

CONF_ZONE: Final = "zone"
CONF_MODEL: Final = "model"
CONF_UNIT: Final = "unit"
CONF_MARKUP: Final = "markup"
CONF_VAT: Final = "vat"

# Sentinel for "follow the model Spotprognos marks as default_model".
MODEL_FOLLOW_DEFAULT: Final = "follow_default"

UNIT_ORE_KWH: Final = "öre/kWh"
UNIT_EUR_MWH: Final = "EUR/MWh"
UNITS: Final = (UNIT_ORE_KWH, UNIT_EUR_MWH)

VAT_RATE: Final = 0.25

DEFAULT_MODEL: Final = MODEL_FOLLOW_DEFAULT
DEFAULT_UNIT: Final = UNIT_ORE_KWH
DEFAULT_MARKUP: Final = 0.0
DEFAULT_VAT: Final = False

"""Constants for the Engrate integration."""

from logging import getLogger

DOMAIN = "engrate"
LOGGER = getLogger(__package__)

API_BASE_URL = "https://api.engrate.io"

CONF_API_KEY = "api_key"
CONF_COUNTRY = "country"
CONF_SYSTEM_OPERATOR_ID = "system_operator_id"
CONF_TARIFF_ID = "tariff_id"
CONF_DATASETS = "datasets"

# Dataset IDs that map to energy sensors (kWh) — use ENERGY device_class filter
ENERGY_DATASET_IDS = {
    "quarter-hourly-energy-offtake",
    "quarter-hourly-energy-injection",
}

# Dataset IDs that map to power/capacity sensors (kW) — use POWER device_class filter
POWER_DATASET_IDS = {
    "yearly-firm-subscribed-offtake-capacity",
    "yearly-firm-subscribed-injection-capacity",
    "yearly-conditional-subscribed-offtake-capacity",
    "yearly-conditional-subscribed-injection-capacity",
    "hourly-available-conditional-offtake-capacity",
    "hourly-available-conditional-injection-capacity",
}

# Dataset IDs for spot prices — use 'mean' stat type from recorder
PRICE_DATASET_IDS = {
    "quarter-hourly-day-ahead-price-se1",
    "quarter-hourly-day-ahead-price-se2",
    "quarter-hourly-day-ahead-price-se3",
    "quarter-hourly-day-ahead-price-se4",
}

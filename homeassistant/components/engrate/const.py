"""Constants for the Engrate integration."""

from logging import getLogger

DOMAIN = "engrate"
LOGGER = getLogger(__package__)

API_BASE_URL = "https://api.engrate.io"

CONF_API_KEY = "api_key"
CONF_SYSTEM_OPERATOR_ID = "system_operator_id"
CONF_TARIFF_ID = "tariff_id"
CONF_DATASETS = "datasets"

ENERGY_COST_DATASET_IDS = {
    "quarter-hourly-day-ahead-price-se1",
    "quarter-hourly-day-ahead-price-se2",
    "quarter-hourly-day-ahead-price-se3",
    "quarter-hourly-day-ahead-price-se4",
}

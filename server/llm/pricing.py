import logging
from pathlib import Path

import yaml  # type: ignore

logger = logging.getLogger(__name__)
CONFIG_PATH = Path("config/models.yaml")

def load_pricing() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH) as f:
            data = yaml.safe_load(f)
            return data.get("pricing_usd_per_million_tokens", {})
    except Exception as e:
        logger.error(f"Error loading pricing: {e}")
        return {}

PRICING_TABLE = load_pricing()

def calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Calculates LLM cost based on input/output tokens using the config."""
    rates = PRICING_TABLE.get(model)
    if not rates:
        return 0.0
    return (tokens_in * rates.get("input", 0) / 1_000_000) + (tokens_out * rates.get("output", 0) / 1_000_000)

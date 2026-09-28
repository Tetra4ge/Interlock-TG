import logging
from pathlib import Path

import yaml  # type: ignore

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config/models.yaml"


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
        logger.warning(f"No pricing entry for model '{model}'; cost recorded as $0.00")
        return 0.0
    input_cost = tokens_in * rates.get("input", 0) / 1_000_000
    output_cost = tokens_out * rates.get("output", 0) / 1_000_000
    return input_cost + output_cost

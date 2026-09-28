import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config/models.yaml"


def load_pricing(path: Path = CONFIG_PATH) -> dict:
    """Load the pricing table from YAML.

    Deliberately does NOT swallow parse errors: a malformed models.yaml means
    the gateway can no longer price calls, so the spend cap can no longer
    protect the user. Failing fast at startup with a clear message beats
    silently treating every model as free.
    """
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("pricing_usd_per_million_tokens", {}) if data else {}


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

from functools import cache
from typing import Any

import yaml

from server.settings import ROOT

PIPELINE_YAML = ROOT / "config/pipeline.yaml"


@cache
def _pipeline_yaml() -> dict[str, Any]:
    if not PIPELINE_YAML.exists():
        return {}
    return yaml.safe_load(PIPELINE_YAML.read_text()) or {}


def pipeline_section(name: str) -> dict[str, Any]:
    """One top-level section of config/pipeline.yaml ({} if absent)."""
    return dict(_pipeline_yaml().get(name) or {})

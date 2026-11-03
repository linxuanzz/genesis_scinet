"""Network Agent parameters.

Every parameter that affects results is declared (with its type) here, and its value may only
come from a config file. Fields therefore have no defaults: a missing or misspelled
key fails at load time instead of silently falling back to some default number.
Later steps add new parameters here as they need them.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, PositiveFloat, PositiveInt, model_validator


class NetAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_seconds: PositiveInt         # ledger slot length; smaller is more precise but costs more bin-packing (slide 23)
    horizon_seconds: PositiveInt      # how far ahead the ledger looks
    reserve_ttl_seconds: PositiveInt  # an uncommitted reserve is released automatically after this (slide 19)
    query_ttl_seconds: PositiveInt    # returned offers can be reserved for this long; also bounds how late a reserved start can be
    max_paths: PositiveInt            # max candidate paths per endpoint pair (fewest hops first)
    rate_step_gbps: PositiveFloat     # offer rates are rounded to this step (slide 7's 40 / 100 / 20 Gbps are all multiples of 10)

    @model_validator(mode="after")
    def _whole_slots(self):
        if self.horizon_seconds % self.slot_seconds:
            raise ValueError("horizon_seconds must be a multiple of slot_seconds")
        return self


def load_config(source: dict | str | Path) -> NetAgentConfig:
    """Load from a dict or a yaml file. The yaml may be a full experiment config, in which case its ``network_agent`` section is used."""
    if not isinstance(source, dict):
        source = yaml.safe_load(Path(source).read_text())
    return NetAgentConfig.model_validate(source.get("network_agent", source))

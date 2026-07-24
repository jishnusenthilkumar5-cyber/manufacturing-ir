from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DispatchPolicy(StrEnum):
    FIFO_FAIR = "fifo-fair"
    PRIORITY = "priority"
    SHORTEST_CYCLE = "shortest-cycle"


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    horizon_s: float = Field(default=86_400.0, gt=0, allow_inf_nan=False)
    warmup_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    seed: int = 1
    replications: int = Field(default=1, ge=1, le=10_000)
    arrival_rates_per_hour: dict[str, float] = Field(default_factory=dict)
    dispatch: DispatchPolicy = DispatchPolicy.FIFO_FAIR

    @model_validator(mode="after")
    def validate_scenario(self) -> "Scenario":
        if self.warmup_s >= self.horizon_s:
            raise ValueError("warmup_s must be less than horizon_s")
        invalid = {
            flow_id: rate
            for flow_id, rate in self.arrival_rates_per_hour.items()
            if rate <= 0 or not float("-inf") < rate < float("inf")
        }
        if invalid:
            raise ValueError("arrival rates must be finite and positive")
        return self

    @property
    def measurement_s(self) -> float:
        return self.horizon_s - self.warmup_s

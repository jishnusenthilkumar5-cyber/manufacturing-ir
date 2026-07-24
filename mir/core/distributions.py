from __future__ import annotations

import random
import sys
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConstantDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["constant"] = "constant"
    value_s: float = Field(gt=0, allow_inf_nan=False)

    def sample(self, rng: random.Random) -> float:
        return self.value_s

    def mean_seconds(self) -> float:
        return self.value_s


class UniformDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["uniform"] = "uniform"
    low_s: float = Field(gt=0, allow_inf_nan=False)
    high_s: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> "UniformDistribution":
        if self.high_s < self.low_s:
            raise ValueError("high_s must be greater than or equal to low_s")
        return self

    def sample(self, rng: random.Random) -> float:
        return rng.uniform(self.low_s, self.high_s)

    def mean_seconds(self) -> float:
        return (self.low_s + self.high_s) / 2.0


class NormalDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["normal"] = "normal"
    mean_s: float = Field(gt=0, allow_inf_nan=False)
    std_s: float = Field(ge=0, allow_inf_nan=False)

    def sample(self, rng: random.Random) -> float:
        if self.std_s == 0:
            return self.mean_s
        for _ in range(10_000):
            value = rng.normalvariate(self.mean_s, self.std_s)
            if value > 0:
                return value
        return sys.float_info.epsilon

    def mean_seconds(self) -> float:
        return self.mean_s


class ExponentialDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["exponential"] = "exponential"
    mean_s: float = Field(gt=0, allow_inf_nan=False)

    def sample(self, rng: random.Random) -> float:
        return rng.expovariate(1.0 / self.mean_s)

    def mean_seconds(self) -> float:
        return self.mean_s


Distribution = Annotated[
    ConstantDistribution
    | UniformDistribution
    | NormalDistribution
    | ExponentialDistribution,
    Field(discriminator="kind"),
]

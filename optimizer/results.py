"""Validated frequency traces and their acquisition provenance."""

from dataclasses import dataclass, field
from typing import Any

import numpy as np


_GHZ_FACTORS = {"Hz": 1e-9, "kHz": 1e-6, "MHz": 1e-3, "GHz": 1.0, "THz": 1e3}


def frequency_to_ghz(values, unit: str) -> np.ndarray:
    if unit not in _GHZ_FACTORS:
        raise ValueError(f"Explicit supported frequency unit required, got {unit!r}")
    axis = np.asarray(values, dtype=float)
    if axis.ndim != 1 or not axis.size or not np.all(np.isfinite(axis)):
        raise ValueError("Frequency axis must be a nonempty finite 1D array")
    axis = axis * _GHZ_FACTORS[unit]
    if np.any(axis <= 0) or np.any(np.diff(axis) <= 0):
        raise ValueError("Frequencies must be positive, unique and increasing")
    return axis


@dataclass(frozen=True)
class TraceData:
    expression: str
    frequencies_ghz: np.ndarray
    values: np.ndarray
    value_unit: str = "dB"
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        axis = frequency_to_ghz(self.frequencies_ghz, "GHz").copy()
        values = np.asarray(self.values, dtype=float).copy()
        if values.shape != axis.shape or not np.all(np.isfinite(values)):
            raise ValueError("Trace values must be finite, 1D and match the frequency axis")
        axis.setflags(write=False)
        values.setflags(write=False)
        object.__setattr__(self, "frequencies_ghz", axis)
        object.__setattr__(self, "values", values)

    def to_dict(self):
        return {"expression": self.expression, "frequency_unit": "GHz", "value_unit": self.value_unit,
                "frequencies": self.frequencies_ghz.tolist(), "values": self.values.tolist(),
                "source": dict(self.source)}


@dataclass
class ResultBundle:
    traces: dict[str, TraceData]
    provenance: dict[str, Any]
    schema_version: int = 1

    def __post_init__(self):
        if not self.traces:
            raise ValueError("ResultBundle requires at least one trace")
        reference = next(iter(self.traces.values())).frequencies_ghz
        for trace in self.traces.values():
            if not np.array_equal(reference, trace.frequencies_ghz):
                raise ValueError("Result traces have different frequency axes")

    def to_dict(self):
        return {"schema_version": self.schema_version, "traces": {
            name: trace.to_dict() for name, trace in self.traces.items()},
            "provenance": dict(self.provenance)}

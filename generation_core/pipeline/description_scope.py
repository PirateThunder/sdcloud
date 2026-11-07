from __future__ import annotations

import re

from .exceptions import ModelValidationError

_SPATIAL = re.compile(r"\bpartial differential equation\b|\bpartial derivative\b|\bpde\b", re.IGNORECASE)
_SPATIAL_DERIVATIVE = re.compile(r"∂\s*(?:²|\^\s*2)?\s*[A-Za-zΑ-ω]+\s*/\s*∂\s*[xyz]\b", re.IGNORECASE)
_STOCHASTIC = re.compile(r"\bstochastic differential\b|\bwiener process\b", re.IGNORECASE)


def validate_description_scope(description: str) -> None:
    bounds = {}
    for match in re.finditer(
        r"\b(initial_time|final_time)\s*=\s*"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z_]+)?",
        description,
        re.IGNORECASE,
    ):
        bounds[match.group(1).casefold()] = (float(match.group(2)), match.group(3))
    if len(bounds) == 2:
        initial, final = bounds["initial_time"], bounds["final_time"]
        if initial[1] == final[1] and final[0] <= initial[0]:
            raise ModelValidationError("final_time must be greater than initial_time")
    if _SPATIAL.search(description) or _SPATIAL_DERIVATIVE.search(description):
        raise ModelValidationError(
            "UNSUPPORTED_CAPABILITY: spatial partial differential equations require a PDE solver; "
            "provide an ordinary differential equation or a finite compartment approximation"
        )
    if _STOCHASTIC.search(description) or re.search(r"\bdW\b", description):
        raise ModelValidationError(
            "UNSUPPORTED_CAPABILITY: stochastic differential equations and Wiener noise require "
            "a stochastic solver; provide a deterministic equation"
        )

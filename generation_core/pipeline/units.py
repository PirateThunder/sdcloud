from __future__ import annotations

import re

UNIT_ALIASES = {
    "person": "person",
    "persons": "person",
    "people": "person",
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "year": "year",
    "years": "year",
    "hour": "hour",
    "hours": "hour",
    "minute": "minute",
    "minutes": "minute",
    "animal": "animal",
    "animals": "animal",
    "rabbit": "rabbit",
    "rabbits": "rabbit",
    "hare": "hare",
    "hares": "hare",
    "fox": "fox",
    "foxes": "fox",
    "task": "task",
    "tasks": "task",
    "item": "item",
    "items": "item",
    "packet": "packet",
    "packets": "packet",
    "atom": "atom",
    "atoms": "atom",
    "mole": "mole",
    "moles": "mole",
    "second": "second",
    "seconds": "second",
    "s": "second",
    "meter": "meter",
    "meters": "meter",
    "m": "meter",
    "kilogram": "kilogram",
    "kilograms": "kilogram",
    "kg": "kilogram",
    "litre": "litre",
    "litres": "litre",
    "liter": "litre",
    "liters": "litre",
    "lit": "litre",
    "l": "litre",
    "coulomb": "coulomb",
    "coulombs": "coulomb",
    "c": "coulomb",
    "ampere": "ampere",
    "amperes": "ampere",
    "a": "ampere",
    "farad": "farad",
    "farads": "farad",
    "f": "farad",
    "ohm": "ohm",
    "ohms": "ohm",
    "volt": "volt",
    "volts": "volt",
    "v": "volt",
    "henry": "henry",
    "henries": "henry",
    "joule": "joule",
    "joules": "joule",
    "j": "joule",
    "watt": "watt",
    "watts": "watt",
    "newton": "newton",
    "newtons": "newton",
    "n": "newton",
    "siemens": "siemens",
}

_DERIVED_UNITS = {
    "ampere": {"coulomb": 1, "second": -1},
    "farad": {"coulomb": 1, "volt": -1},
    "ohm": {"second": 1, "farad": -1},
    "volt": {"joule": 1, "coulomb": -1},
    "henry": {"volt": 1, "second": 1, "ampere": -1},
    "joule": {"newton": 1, "meter": 1},
    "watt": {"joule": 1, "second": -1},
    "newton": {"kilogram": 1, "meter": 1, "second": -2},
    "siemens": {"ampere": 1, "volt": -1},
}


def _named_units(name: str, power: int) -> dict[str, int]:
    normalized = re.sub(r"\s+", "_", name.strip().lower())
    if normalized in {"", "1", "dimensionless"}:
        return {}
    if normalized.startswith("per_"):
        return _named_units(normalized.removeprefix("per_"), -power)
    if "_per_" in normalized:
        numerator, *denominators = normalized.split("_per_")
        result = _named_units(numerator, power) if numerator else {}
        for denominator in denominators:
            result = combine(result, _named_units(denominator, power), -1)
        return result
    if match := re.fullmatch(r"(.+)\^(-?\d+)", normalized):
        return _named_units(match.group(1), power * int(match.group(2)))
    exponent = 1
    for suffix, value in (("_squared", 2), ("_cubed", 3)):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            exponent = value
            break
    return {UNIT_ALIASES.get(normalized, normalized): power * exponent}


def canonical_units(units: dict[str, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, power in units.items():
        result = combine(result, _named_units(name, power))
    for _ in range(len(_DERIVED_UNITS) + 1):
        changed = False
        expanded = {}
        for name, power in result.items():
            definition = _DERIVED_UNITS.get(name)
            if definition is None:
                expanded[name] = expanded.get(name, 0) + power
            else:
                changed = True
                for base, exponent in definition.items():
                    expanded[base] = expanded.get(base, 0) + power * exponent
        result = {name: power for name, power in expanded.items() if power}
        if not changed:
            return result
    raise ValueError("cyclic derived unit definitions")


def combine(left: dict[str, int], right: dict[str, int], sign: int = 1) -> dict[str, int]:
    result = dict(left)
    for name, power in right.items():
        result[name] = result.get(name, 0) + sign * power
        if not result[name]:
            del result[name]
    return result


def _unit_name(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        return None
    return UNIT_ALIASES.get(normalized, normalized)


def canonical_time_unit(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if normalized in {"time_unit", "time_units"}:
        return "time"
    return UNIT_ALIASES.get(normalized, normalized)


def parse_units(value: str | None) -> dict[str, int] | None:
    if not value or not value.strip():
        return {} if value is not None and not value.strip() else None
    text = value.strip()
    text = re.sub(r"\s*\[[^]]*\]\s*$", "", text)
    tokens = re.findall(r"\s*(?:([*/^()])|(-?\d+)|([^*/^()]+))", text)
    if not tokens:
        return None
    parts: list[str] = []
    for operator, number, name in tokens:
        parts.append(operator or number or name.strip())
    position = 0

    def factor() -> dict[str, int] | None:
        nonlocal position
        if position >= len(parts):
            return None
        token = parts[position]
        if token == "(":
            position += 1
            result = expression()
            if position >= len(parts) or parts[position] != ")":
                return None
            position += 1
        elif token == "1":
            position += 1
            result = {}
        elif token in {"*", "/", "^", ")", ""} or re.fullmatch(r"-?\d+", token):
            return None
        else:
            position += 1
            name = _unit_name(token)
            if name is None:
                return None
            result = {name: 1}
        if position < len(parts) and parts[position] == "^":
            position += 1
            if position >= len(parts) or not re.fullmatch(r"-?\d+", parts[position]):
                return None
            power = int(parts[position])
            position += 1
            result = {name: exponent * power for name, exponent in result.items()}
        return result

    def expression() -> dict[str, int] | None:
        nonlocal position
        result = factor()
        if result is None:
            return None
        while position < len(parts) and parts[position] in {"*", "/"}:
            operator = parts[position]
            position += 1
            right = factor()
            if right is None:
                return None
            result = combine(result, right, 1 if operator == "*" else -1)
        return result

    result = expression()
    if result is None or position != len(parts):
        return None
    return result


def format_units(units: dict[str, int] | None, raw: str | None = None) -> str:
    if raw is not None:
        return raw
    if not units:
        return ""
    positive = []
    negative = []
    for name, power in sorted(units.items()):
        target = positive if power > 0 else negative
        target.append(name if abs(power) == 1 else f"{name}^{abs(power)}")
    numerator = "*".join(positive) or "1"
    denominator = "*".join(negative)
    return numerator + (
        f"/({denominator})" if len(negative) > 1 else f"/{denominator}" if denominator else ""
    )

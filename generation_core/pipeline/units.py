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
}


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

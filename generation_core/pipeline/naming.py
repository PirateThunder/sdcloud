import hashlib
import re


def identifier(label: str, used: set[str] | None = None) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower()
    if not value or not value[0].isalpha() and not value.startswith("_"):
        value = f"v_{value}" if value else "variable"
    value = value[:80]
    if value in {"time", "np", "min", "max", "abs", "integ"}:
        value = f"var_{value}"
    if used is None or value not in used:
        return value
    suffix = hashlib.sha256(label.encode()).hexdigest()[:8]
    candidate = f"{value}_{suffix}"
    index = 2
    while candidate in used:
        candidate = f"{value}_{suffix}_{index}"
        index += 1
    return candidate

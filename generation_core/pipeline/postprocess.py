"""Compatibility helpers for callers of the legacy equation postprocessor."""


def post_process_equations(variables: list[dict], equations: list[dict]) -> list[dict]:
    return [dict(equation) for equation in equations]

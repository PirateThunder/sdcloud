from __future__ import annotations

import itertools
import re
from pathlib import Path

from .exceptions import ModelValidationError
from .ir import dependencies, lit, walk
from .naming import identifier
from .schemas import (
    ArrayExpression,
    Dimension,
    Expression,
    ModelDocument,
    TimeSettings,
)
from .units import parse_units

_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_SIGNED = rf"[+-]?{_NUMBER}"
_ARRAY_ROW = rf"{_SIGNED}(?:\s*,\s*{_SIGNED})*"
_ARRAY = re.compile(rf"^{_ARRAY_ROW}(?:\s*;\s*{_ARRAY_ROW})*;?$")
_DIMENSION = re.compile(
    r"(?ms)^(?P<label>[A-Za-z_][A-Za-z0-9_ ]*)\s*:\s*"
    r"(?P<rhs>\([^\n~]+?\)|[^\n~]+?)(?=\n[ \t]*~)"
    r"(?:\n[ \t]*~[ \t]*[^\n]*)?"
    r"(?:\n[ \t]*~[ \t]*(?P<comment>.*?)\|)?"
)


def remove_dimensions(body: str) -> str:
    return _DIMENSION.sub("", body)


def _elements(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    match = re.fullmatch(r"([A-Za-z_]+)(\d+)\s*-\s*(?:\1)?(\d+)", value)
    if match is not None:
        start, end = int(match.group(2)), int(match.group(3))
        if end < start:
            raise ModelValidationError(f"descending subscript range is not supported: {value}")
        return [f"{match.group(1)}{index}" for index in range(start, end + 1)]
    return [value] if value else []


def extract_dimensions(body: str) -> tuple[list[Dimension], dict[str, list[str]]]:
    dimensions = []
    element_dimensions = {}
    used = set()
    for match in _DIMENSION.finditer(body):
        label = match.group("label").strip()
        elements = _elements(match.group("rhs"))
        if not elements:
            continue
        dimension_id = identifier(label, used)
        used.add(dimension_id)
        dimensions.append(Dimension(id=dimension_id, elements=elements))
        for element in elements:
            element_dimensions.setdefault(element, []).append(dimension_id)
    return dimensions, element_dimensions


def _label_details(
    label: str, dimensions: dict[str, Dimension], element_dimensions: dict[str, list[str]]
) -> tuple[str, list[str], dict[str, str]]:
    base = label.split("[", 1)[0].strip()
    if "[" not in label:
        return base, [], {}
    if not label.endswith("]"):
        raise ModelValidationError(f"unclosed subscript in variable label: {label}")
    subscripts = []
    indices = {}
    values = label.split("[", 1)[1][:-1].split(",")
    for raw in values:
        value = raw.strip()
        if value in dimensions:
            dimension = value
            element = "*"
        else:
            candidates = element_dimensions.get(value, [])
            dimension = candidates[0] if len(candidates) == 1 else None
            if dimension is None and len(candidates) > 1:
                dimension = next((item for item in candidates if item not in indices), None)
            element = value
        if dimension is None or dimension in indices:
            raise ModelValidationError(f"invalid subscript {value} in {label}")
        subscripts.append(dimension)
        indices[dimension] = element
    return base, subscripts, indices


def _numeric_array(source: str) -> ArrayExpression | None:
    if "," not in source and ";" not in source:
        return None
    if _ARRAY.fullmatch(source) is None:
        return None
    rows = [row.strip() for row in source.rstrip(";").split(";")]
    values = []
    width = None
    for row in rows:
        numbers = [float(item.strip()) for item in row.split(",")]
        if width is None:
            width = len(numbers)
        elif len(numbers) != width:
            raise ModelValidationError("subscripted array rows have different lengths")
        values.extend(lit(number) for number in numbers)
    return ArrayExpression(
        op="array",
        values=values,
        shape=[len(rows), width] if len(rows) > 1 else None,
    )


def _merge_expressions(
    records: list[dict], field: str, dimensions: dict[str, Dimension]
) -> Expression:
    if len(records) == 1:
        return records[0][field]
    subscripts = records[0]["subscripts"]
    if not subscripts or any(record["subscripts"] != subscripts for record in records):
        raise ModelValidationError("inconsistent subscripts in grouped variable assignments")
    if any(isinstance(record[field], ArrayExpression) for record in records):
        raise ModelValidationError("nested subscripted array assignments are not supported")
    element_lists = [dimensions[name].elements for name in subscripts]
    expected = list(itertools.product(*element_lists))
    values = []
    for elements in expected:
        candidates = []
        for record in records:
            if all(record["indices"].get(name) in {element, "*"} for name, element in zip(subscripts, elements, strict=True)):
                specificity = sum(record["indices"].get(name) != "*" for name in subscripts)
                candidates.append((specificity, record[field]))
        if not candidates:
            raise ModelValidationError(f"incomplete subscripted assignments for {elements}")
        best = max(score for score, _ in candidates)
        matches = [expression.model_dump(mode="json") for score, expression in candidates if score == best]
        if len(matches) != 1:
            raise ModelValidationError(f"ambiguous subscripted assignments for {elements}")
        values.append(next(expression for score, expression in candidates if score == best))
    return ArrayExpression(
        op="array",
        values=values,
        shape=[len(expected)] if len(expected) > 1 else None,
    )


def import_subscripted(
    raw: list[dict],
    controls: dict,
    tables: list,
    tables_names: dict[str, str],
    body: str,
    source_name: str,
    source: str,
) -> ModelDocument:
    from .formats import ExpressionParser, _finish, _infer_topology, _number, _source_hash

    dimensions_list, element_dimensions = extract_dimensions(source)
    dimensions = {item.id: item for item in dimensions_list}
    if not dimensions:
        raise ModelValidationError("subscripted model has no dimension definitions")
    used = set()
    names = {}
    details = []
    for item in raw:
        base, subscripts, indices = _label_details(
            item["label"], dimensions, element_dimensions
        )
        if base not in names:
            names[base] = identifier(base, used)
            used.add(names[base])
        details.append(
            {
                **item,
                "base": base,
                "id": names[base],
                "subscripts": subscripts,
                "indices": indices,
            }
        )
    variable_subscripts = {
        item["id"]: item["subscripts"] for item in details if item["subscripts"]
    }
    groups = {}
    for item in details:
        expression = (
            _numeric_array(item["rhs"])
            or ExpressionParser(
                item["rhs"],
                names,
                tables_names,
                subscripts=variable_subscripts,
                element_dimensions=element_dimensions,
            ).parse()
        )
        common = {
            "id": item["id"],
            "label": item["base"],
            "description": item["description"] or None,
            "units": parse_units(item["units"]),
            "units_raw": item["units"] or None,
            "subscripts": item["subscripts"],
        }
        if expression.op == "call" and expression.name == "integ":
            if len(expression.args) != 2:
                raise ModelValidationError(f"invalid INTEG for {item['label']}")
            record = {
                **common,
                "kind": "stock",
                "initial": expression.args[1],
                "derivative": expression.args[0],
            }
        else:
            record = {**common, "kind": "auxiliary", "expression": expression}
        record["indices"] = item["indices"]
        groups.setdefault(item["id"], []).append(record)

    variables = []
    flows = set()
    for group in groups.values():
        first = group[0]
        common = {key: value for key, value in first.items() if key != "indices"}
        if first["kind"] == "stock":
            derivatives = [record["derivative"].model_dump(mode="json") for record in group]
            if any(item != derivatives[0] for item in derivatives[1:]):
                raise ModelValidationError("element-specific stock derivatives are not supported")
            variable = {
                **common,
                "initial": _merge_expressions(group, "initial", dimensions),
                "derivative": first["derivative"],
            }
            flows.update(dependencies(first["derivative"]))
        else:
            variable = {
                **common,
                "expression": _merge_expressions(group, "expression", dimensions),
            }
        variables.append(variable)

    for variable in variables:
        if variable["kind"] == "stock":
            continue
        if variable["id"] in flows:
            variable["kind"] = "flow"
            variable["topology_status"] = "missing"
        elif not dependencies(variable["expression"]) and not any(
            node.op == "time" or (node.op == "call" and node.name in {
                "step", "pulse", "pulse_train", "ramp", "delay1", "delay3",
                "delay1i", "delay3i", "smooth", "smooth3", "smoothi", "smooth3i", "initial",
            })
            for record in groups[variable["id"]]
            for node in walk(record["expression"])
        ):
            variable["kind"] = "constant"
    _infer_topology(variables)
    unit = next(
        (units for name, (_, units) in controls.items() if name == "FINAL TIME" and units),
        "time",
    )
    document = ModelDocument(
        name=Path(source_name).stem,
        description="Imported Vensim model",
        time=TimeSettings(
            unit=parse_units(unit) and next(iter(parse_units(unit))) or unit or "time",
            initial_time=_number(controls.get("INITIAL TIME", ("0", ""))[0]),
            final_time=_number(controls.get("FINAL TIME", ("100", ""))[0]),
            time_step=_number(controls.get("TIME STEP", ("0.25", ""))[0]),
            saveper=_number(controls.get("TIME STEP", ("0.25", ""))[0])
            if controls.get("SAVEPER", ("TIME STEP", ""))[0].strip().upper() == "TIME STEP"
            else _number(controls["SAVEPER"][0]),
        ),
        variables=variables,
        tables=tables,
        dimensions=dimensions_list,
        provenance={
            "kind": "vensim_import",
            "source_name": source_name,
            "source_sha256": _source_hash(source),
        },
    )
    return _finish(document)

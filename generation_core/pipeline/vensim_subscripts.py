from __future__ import annotations

import itertools
import math
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
_DIMENSION_MAP = re.compile(
    r"(?ms)^(?P<label>[A-Za-z_][A-Za-z0-9_ ]*)\s*<->\s*"
    r"(?P<target>[A-Za-z_][A-Za-z0-9_ ]*)(?=\n[ \t]*~)"
    r"(?:\n[ \t]*~[ \t]*[^\n]*)?"
    r"(?:\n[ \t]*~[ \t]*(?P<comment>.*?)\|)?"
)


def remove_dimensions(body: str) -> str:
    return _DIMENSION_MAP.sub("", _DIMENSION.sub("", body))


def _import_units(value: str) -> dict[str, int] | None:
    return None if value.strip().lower() in {"", "units"} else parse_units(value)


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
    from .formats import _normalize_inline_metadata

    body = _normalize_inline_metadata(body)
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
    by_label = {identifier(item.id, set()): item for item in dimensions}
    for match in _DIMENSION_MAP.finditer(body):
        target = by_label.get(identifier(match.group("target").strip(), set()))
        if target is None:
            raise ModelValidationError(
                f"unknown dimension alias target: {match.group('target').strip()}"
            )
        alias_id = identifier(match.group("label").strip(), used)
        used.add(alias_id)
        dimensions.append(Dimension(id=alias_id, elements=target.elements))
        for element in target.elements:
            element_dimensions.setdefault(element, []).append(alias_id)
    return dimensions, element_dimensions


def _index_values(
    values: list[str],
    dimensions: dict[str, Dimension],
    element_dimensions: dict[str, list[str]],
    label: str,
) -> tuple[list[str], dict[str, str]]:
    subscripts = []
    indices = {}
    for raw in values:
        value = raw.strip()
        normalized = identifier(value, set())
        if normalized in dimensions:
            dimension = normalized
            element = "*"
        else:
            candidates = element_dimensions.get(value, [])
            dimension = candidates[0] if len(candidates) == 1 else None
            if dimension is None and len(candidates) > 1:
                unused = [item for item in candidates if item not in indices]
                if unused:
                    dimension = max(unused, key=lambda item: len(dimensions[item].elements))
            element = value
        if dimension is None or dimension in indices:
            raise ModelValidationError(f"invalid subscript {value} in {label}")
        subscripts.append(dimension)
        indices[dimension] = element
    return subscripts, indices


def _label_details(
    label: str, dimensions: dict[str, Dimension], element_dimensions: dict[str, list[str]]
) -> tuple[str, list[str], dict[str, str], list[dict[str, str]]]:
    exception_indices = []
    if ":EXCEPT:" in label:
        label, exception_source = label.split(":EXCEPT:", 1)
        for values in re.findall(r"\[([^\]]+)\]", exception_source):
            _, indices = _index_values(
                values.split(","), dimensions, element_dimensions, label
            )
            exception_indices.append(indices)
    label = label.strip()
    base = label.split("[", 1)[0].strip()
    if "[" not in label:
        return base, [], {}, exception_indices
    if not label.endswith("]"):
        raise ModelValidationError(f"unclosed subscript in variable label: {label}")
    subscripts, indices = _index_values(
        label.split("[", 1)[1][:-1].split(","),
        dimensions,
        element_dimensions,
        label,
    )
    return base, subscripts, indices, exception_indices


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


def _merged_subscripts(records: list[dict], dimensions: dict[str, Dimension]) -> list[str]:
    lists = [record["subscripts"] for record in records]
    if len(lists) == 1:
        return lists[0]
    if not lists[0] or any(len(items) != len(lists[0]) for items in lists):
        raise ModelValidationError("inconsistent subscripts in grouped variable assignments")
    result = []
    for axis in range(len(lists[0])):
        candidates = list(dict.fromkeys(items[axis] for items in lists))
        elements = {
            element for name in candidates for element in dimensions[name].elements
        }
        containing = [
            name
            for name in dimensions
            if len(dimensions[name].elements) == len(elements)
            and elements == set(dimensions[name].elements)
        ]
        selected = next((name for name in candidates if name in containing), None)
        if selected is None and containing:
            selected = containing[0]
        if selected is None:
            raise ModelValidationError(
                f"cannot unify subscript ranges on axis {axis + 1}: {candidates}"
            )
        result.append(selected)
    for axis, selected in enumerate(result):
        covered = []
        for record in records:
            local = record["subscripts"][axis]
            index = record["indices"][local]
            values = dimensions[local].elements if index == "*" else [index]
            covered.extend(value for value in values if value not in covered)
        if set(covered) == set(dimensions[selected].elements):
            continue
        if not set(covered) <= set(dimensions[selected].elements):
            raise ModelValidationError(f"subscript range escapes its dimension on axis {axis + 1}")
        elements = [value for value in dimensions[selected].elements if value in covered]
        existing = next(
            (name for name, dimension in dimensions.items() if dimension.elements == elements),
            None,
        )
        if existing is None:
            existing = identifier(f"{records[0]['id']}_subscript_{axis + 1}", set(dimensions))
            dimensions[existing] = Dimension(id=existing, elements=elements)
        result[axis] = existing
    return result


def _source_axis(
    name: str, local: list[str], dimensions: dict[str, Dimension]
) -> int:
    axes = [index for index, candidate in enumerate(local) if candidate == name]
    if not axes:
        source_elements = set(dimensions[name].elements)
        axes = [
            index
            for index, candidate in enumerate(local)
            if source_elements <= set(dimensions[candidate].elements)
        ]
    if len(axes) != 1:
        raise ModelValidationError(f"cannot map subscript {name} to grouped assignments")
    return axes[0]


def _mapped_indices(
    indices: dict[str, str],
    local: list[str],
    merged: list[str],
    dimensions: dict[str, Dimension],
) -> dict[str, str]:
    return {
        merged[_source_axis(name, local, dimensions)]: element
        for name, element in indices.items()
    }


def _exception_matches(
    exception: dict[str, str],
    record: dict,
    merged: list[str],
    elements: tuple[str, ...],
    dimensions: dict[str, Dimension],
) -> bool:
    for axis, (_, element) in enumerate(zip(merged, elements, strict=True)):
        source = next(
            (
                candidate
                for candidate in exception
                if _source_axis(candidate, record["subscripts"], dimensions) == axis
            ),
            None,
        )
        if (
            source is None
            or exception[source] not in {element, "*"}
            or element not in dimensions[source].elements
        ):
            return False
    return True


def _merge_expressions(
    records: list[dict], field: str, dimensions: dict[str, Dimension]
) -> Expression:
    if len(records) == 1:
        record = records[0]
        expression = record[field]
        element_lists = [dimensions[name].elements for name in record["subscripts"]]
        if (
            record["subscripts"]
            and not isinstance(expression, ArrayExpression)
            and all(value == "*" for value in record["indices"].values())
            and any(
                node.op == "index" and "*" in node.indices.values()
                for node in walk(expression)
            )
        ):
            count = math.prod(len(elements) for elements in element_lists)
            return ArrayExpression(
                op="array",
                values=[expression for _ in range(count)],
                shape=[len(elements) for elements in element_lists],
            )
        return expression
    subscripts = _merged_subscripts(records, dimensions)
    element_lists = [dimensions[name].elements for name in subscripts]
    expected = list(itertools.product(*element_lists))
    values = []
    for elements in expected:
        candidates = []
        for record in records:
            indices = _mapped_indices(record["indices"], record["subscripts"], subscripts, dimensions)
            if not all(
                indices.get(name) in {element, "*"}
                and element in dimensions[record["subscripts"][axis]].elements
                for axis, (name, element) in enumerate(
                    zip(subscripts, elements, strict=True)
                )
            ):
                continue
            if any(
                _exception_matches(exception, record, subscripts, elements, dimensions)
                for exception in record["exceptions"]
            ):
                continue
            expression = record[field]
            if isinstance(expression, ArrayExpression):
                coordinates = tuple(
                    element if record["indices"][local] == "*" else record["indices"][local]
                    for local, element in zip(record["subscripts"], elements, strict=True)
                )
                local_elements = list(
                    itertools.product(
                        *(
                            dimensions[local].elements
                            if record["indices"][local] == "*"
                            else [record["indices"][local]]
                            for local in record["subscripts"]
                        )
                    )
                )
                if coordinates not in local_elements or len(expression.values) != len(local_elements):
                    raise ModelValidationError("incompatible nested subscripted array assignment")
                expression = expression.values[local_elements.index(coordinates)]
            specificity = sum(indices.get(name) != "*" for name in subscripts)
            candidates.append((specificity, expression))
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
        shape=[len(elements) for elements in element_lists] if len(expected) > 1 else None,
    )


def _rename_dimensions(value, names: dict[str, str]):
    if isinstance(value, list):
        return [_rename_dimensions(item, names) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _rename_dimensions(item, names) for key, item in value.items()}
    if result.get("op") == "index":
        result["indices"] = {
            names.get(name, name): element
            for name, element in result["indices"].items()
        }
    elif result.get("op") == "ref" and result.get("name") in names:
        result["name"] = names[result["name"]]
    return result


def _unify_equivalent_dimensions(
    variables: list[dict], dimensions: dict[str, Dimension]
) -> None:
    groups = {}
    for name, dimension in dimensions.items():
        groups.setdefault(tuple(dimension.elements), []).append(name)
    names = {}
    for group in groups.values():
        if len(group) < 2 or any(
            len(set(variable["subscripts"]) & set(group)) > 1 for variable in variables
        ):
            continue
        names.update({name: group[0] for name in group[1:]})
    if not names:
        return
    for variable in variables:
        variable["subscripts"] = [names.get(name, name) for name in variable["subscripts"]]
        for field in ("initial", "derivative", "expression"):
            if variable.get(field) is not None:
                variable[field] = _rename_dimensions(
                    variable[field].model_dump(mode="json"), names
                )
    for name in names:
        del dimensions[name]


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
        base, subscripts, indices, exception_indices = _label_details(
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
                "exceptions": exception_indices,
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
            "units": _import_units(item["units"]),
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
        record["exceptions"] = item["exceptions"]
        groups.setdefault(item["id"], []).append(record)

    variables = []
    flows = set()
    for group in groups.values():
        first = group[0]
        common = {
            key: value for key, value in first.items() if key not in {"indices", "exceptions"}
        }
        common["subscripts"] = _merged_subscripts(group, dimensions)
        if first["kind"] == "stock":
            variable = {
                **common,
                "initial": _merge_expressions(group, "initial", dimensions),
                "derivative": _merge_expressions(group, "derivative", dimensions),
            }
            flows.update(dependencies(variable["derivative"]))
        else:
            variable = {
                **common,
                "expression": _merge_expressions(group, "expression", dimensions),
            }
        variables.append(variable)

    _unify_equivalent_dimensions(variables, dimensions)
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
        dimensions=list(dimensions.values()),
        provenance={
            "kind": "vensim_import",
            "source_name": source_name,
            "source_sha256": _source_hash(source),
        },
    )
    return _finish(document)

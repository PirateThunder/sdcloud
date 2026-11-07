from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .codegen import expression_to_vensim
from .exceptions import ModelValidationError
from .ir import binary, call, dependencies, lit, ref, time, unary
from .legacy import flow_sign
from .naming import identifier
from .schemas import (
    ArrayExpression,
    CompareExpression,
    Expression,
    IndexedExpression,
    LookupTable,
    ModelDocument,
    SimulationResult,
    TimeSettings,
)
from .units import format_units, parse_units
from .validation import finalize_model

_CONTROL_NAMES = {"INITIAL TIME", "FINAL TIME", "TIME STEP", "SAVEPER"}
_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


@dataclass(frozen=True)
class Token:
    kind: str
    value: str


class ExpressionParser:
    def __init__(
        self,
        source: str,
        names: dict[str, str],
        tables: dict[str, str],
        *,
        subscripts: dict[str, list[str]] | None = None,
        element_dimensions: dict[str, list[str]] | None = None,
    ) -> None:
        self.tokens = self._tokenize(source)
        self.position = 0
        self.names = names
        self.tables = tables
        self.subscripts = subscripts or {}
        self.element_dimensions = element_dimensions or {}

    @staticmethod
    def _tokenize(source: str) -> list[Token]:
        tokens = []
        position = 0
        while position < len(source):
            match = re.match(r"\s+", source[position:])
            if match:
                position += len(match.group())
                continue
            match = re.match(_NUMBER, source[position:])
            if match:
                tokens.append(Token("number", match.group()))
                position += len(match.group())
                continue
            if source[position] == '"':
                end = source.find('"', position + 1)
                if end < 0:
                    raise ModelValidationError("unterminated quoted variable name")
                tokens.append(Token("name", source[position + 1 : end]))
                position = end + 1
                continue
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[position:])
            if match:
                tokens.append(Token("name", match.group()))
                position += len(match.group())
                continue
            match = re.match(r"<=|>=|<>|!=|==|[+\-*/^(),<>=\[\]]", source[position:])
            if not match:
                raise ModelValidationError(f"unsupported expression character: {source[position]}")
            tokens.append(Token("operator", match.group()))
            position += len(match.group())
        tokens.append(Token("eof", ""))
        return tokens

    def parse(self) -> Expression:
        result = self._expression(0)
        if self.tokens[self.position].kind != "eof":
            raise ModelValidationError(f"unexpected token: {self.tokens[self.position].value}")
        return result

    def _expression(self, precedence: int) -> Expression:
        left = self._atom()
        operators = {
            "or": (1, "or"),
            "and": (2, "and"),
            "<": (3, "lt"),
            "<=": (3, "le"),
            ">": (3, "gt"),
            ">=": (3, "ge"),
            "=": (3, "eq"),
            "==": (3, "eq"),
            "<>": (3, "ne"),
            "!=": (3, "ne"),
            "+": (4, "add"),
            "-": (4, "sub"),
            "*": (5, "mul"),
            "/": (5, "div"),
            "^": (6, "pow"),
        }
        while True:
            token = self.tokens[self.position]
            value = token.value.lower()
            if value not in operators or operators[value][0] < precedence:
                break
            binding, op = operators[value]
            self.position += 1
            right = self._expression(binding if op == "pow" else binding + 1)
            if op in {"lt", "le", "gt", "ge", "eq", "ne"}:
                left = CompareExpression(op=op, args=(left, right))
            elif op in {"and", "or"}:
                from .schemas import BooleanExpression

                left = BooleanExpression(op=op, args=[left, right])
            else:
                left = binary(op, left, right)
        return left

    def _atom(self) -> Expression:
        token = self.tokens[self.position]
        if token.value in {"+", "-"} or token.value.lower() == "not":
            self.position += 1
            return unary(
                "neg" if token.value == "-" else "pos" if token.value == "+" else "not",
                self._expression(6),
            )
        if token.value == "(":
            self.position += 1
            result = self._expression(0)
            if self.tokens[self.position].value != ")":
                raise ModelValidationError("unclosed expression parenthesis")
            self.position += 1
            return result
        if token.kind == "number":
            self.position += 1
            return lit(float(token.value))
        if token.kind != "name":
            raise ModelValidationError(f"expected expression, got: {token.value}")
        parts = []
        while self.tokens[self.position].kind == "name":
            parts.append(self.tokens[self.position].value)
            self.position += 1
        name = " ".join(parts)
        if self.tokens[self.position].value == "[":
            variable = self._variable(name)
            return self._parse_indices(variable)
        if self.tokens[self.position].value == "(":
            self.position += 1
            args = []
            if self.tokens[self.position].value != ")":
                while True:
                    args.append(self._expression(0))
                    if self.tokens[self.position].value != ",":
                        break
                    self.position += 1
            if self.tokens[self.position].value != ")":
                raise ModelValidationError("unclosed function call")
            self.position += 1
            table = (
                self.tables.get(name)
                or self.tables.get(name.replace("_", " "))
                or self.tables.get(name.replace(" ", "_"))
            )
            if table is not None and len(args) == 1:
                from .schemas import LookupExpression

                return LookupExpression(op="lookup", table=table, arg=args[0])
            aliases = {"ln": "log", "log": "log10", "pow": "power"}
            function = re.sub(r"[\s_]+", "_", name.lower())
            function = aliases.get(function, function)
            if function in {"delay1", "delay3", "smooth", "smooth3"} and len(args) == 3:
                function = f"{function}i"
            return call(function, *args)
        if name.lower() == "time":
            return time()
        return ref(self._variable(name))

    def _variable(self, name: str) -> str:
        variable = (
            self.names.get(name)
            or self.names.get(name.replace("_", " "))
            or self.names.get(name.replace(" ", "_"))
        )
        if variable is None and any(name in dimensions for dimensions in self.subscripts.values()):
            return name
        if variable is None:
            raise ModelValidationError(f"unknown variable in imported expression: {name}")
        return variable

    def _parse_indices(self, variable: str) -> IndexedExpression:
        dimensions = self.subscripts.get(variable, [])
        self.position += 1
        indices = {}
        while True:
            parts = []
            while self.tokens[self.position].kind in {"name", "number"}:
                parts.append(self.tokens[self.position].value)
                self.position += 1
            if not parts:
                raise ModelValidationError("empty or invalid subscript index")
            value = " ".join(parts)
            normalized = identifier(value, set())
            available_dimensions = {
                item for candidates in self.element_dimensions.values() for item in candidates
            }
            if normalized in dimensions:
                dimension = normalized
                element = "*"
            elif normalized in available_dimensions:
                source_elements = {
                    element
                    for element, candidates in self.element_dimensions.items()
                    if normalized in candidates
                }
                candidates = [
                    item
                    for item in dimensions
                    if source_elements
                    <= {
                        element
                        for element, names in self.element_dimensions.items()
                        if item in names
                    }
                ]
                dimension = candidates[0] if len(candidates) == 1 else None
                element = "*"
            else:
                candidates = self.element_dimensions.get(value, [])
                dimension = candidates[0] if len(candidates) == 1 else None
                if dimension is None and len(indices) < len(dimensions):
                    dimension = dimensions[len(indices)]
                element = value
            if dimension not in dimensions or dimension in indices:
                raise ModelValidationError(
                    f"invalid subscript {value} for {variable}; expected {dimensions}"
                )
            indices[dimension] = element
            if self.tokens[self.position].value == "]":
                self.position += 1
                return IndexedExpression(
                    op="index",
                    name=variable,
                    indices={name: indices[name] for name in dimensions},
                )
            if self.tokens[self.position].value != ",":
                raise ModelValidationError("unclosed subscript expression")
            self.position += 1


def _clean_label(value: str) -> str:
    return value.strip().strip('"').strip()


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _stock_derivative(
    inflows: list[str], outflows: list[str], names: dict[str, str]
) -> Expression | None:
    terms = [ref(names[name]) for name in inflows]
    terms.extend(unary("neg", ref(names[name])) for name in outflows)
    if not terms:
        return None
    result = terms[0]
    for term in terms[1:]:
        result = binary("add", result, term)
    return result


def _derivative_sign(expression: Expression, flow_id: str) -> int:
    if isinstance(expression, ArrayExpression):
        signs = {flow_sign(value, flow_id) for value in expression.values}
        nonzero = signs - {0}
        return nonzero.pop() if len(nonzero) == 1 else 0
    return flow_sign(expression, flow_id)


def _infer_topology(variables: list[dict]) -> None:
    for flow in (item for item in variables if item["kind"] == "flow"):
        positive = []
        negative = []
        for stock in (item for item in variables if item["kind"] == "stock"):
            sign = _derivative_sign(stock["derivative"], flow["id"])
            if sign > 0:
                positive.append(stock["id"])
            elif sign < 0:
                negative.append(stock["id"])
        if len(positive) == 1 and len(negative) == 1:
            flow["source"] = {"kind": "stock", "id": negative[0]}
            flow["target"] = {"kind": "stock", "id": positive[0]}
        elif len(positive) == 1 and not negative:
            flow["source"] = {"kind": "cloud", "id": f"source_{flow['id']}"}
            flow["target"] = {"kind": "stock", "id": positive[0]}
        elif len(negative) == 1 and not positive:
            flow["source"] = {"kind": "stock", "id": negative[0]}
            flow["target"] = {"kind": "cloud", "id": f"sink_{flow['id']}"}
        else:
            flow["topology_status"] = "missing"
            continue
        flow["topology_status"] = "inferred"


def _finish(document: ModelDocument) -> ModelDocument:
    finalized = finalize_model(document)
    errors = [item for item in finalized.validation.issues if item.severity == "error"]
    if errors:
        raise ModelValidationError(
            "; ".join(f"{item.code} at {item.path}: {item.message}" for item in errors[:10])
        )
    return finalized


def _extract_vensim_tables(body: str) -> tuple[str, list[LookupTable], dict[str, str]]:
    pattern = re.compile(
        r"(?ms)^(?P<label>[^=\n]+?)\s*\(\s*(?P<body>\[.*?)(?=\n\s*~|\Z)"
        r"(?:\n\s*~\s*(?P<units>[^\n]*))?"
        r"(?:\n\s*~\s*(?P<comment>.*?)\|)?"
    )
    tables = []
    names = {}
    for match in pattern.finditer(body):
        label = _clean_label(match.group("label"))
        points_source = match.group("body").split("],", 1)[-1]
        signed = rf"[+-]?{_NUMBER}"
        points = [
            (float(x), float(y))
            for x, y in re.findall(rf"\(\s*({signed})\s*,\s*({signed})\s*\)", points_source)
        ]
        if len(points) < 2:
            raise ModelValidationError(f"invalid Vensim lookup table: {label}")
        table_id = identifier(label, set(names.values()))
        names[label] = table_id
        tables.append(
            LookupTable(
                id=table_id,
                label=label,
                points=points,
                y_units=parse_units(match.group("units")),
            )
        )
    return pattern.sub("", body), tables, names


def _normalize_inline_metadata(source: str) -> str:
    result = []
    in_quotes = False
    escaped = False
    index = 0
    while index < len(source):
        if source.startswith("~~|", index) and not in_quotes:
            result.append("\n~\n~ |")
            index += 3
            escaped = False
            continue
        character = source[index]
        result.append(character)
        if character == '"' and not escaped:
            in_quotes = not in_quotes
        escaped = not escaped if character == "\\" else False
        index += 1
    return "".join(result)


def import_vensim(source: str, *, source_name: str = "model.mdl") -> ModelDocument:
    body = source.split("\\\\\\---/// Sketch information", 1)[0].replace("{UTF-8}", "")
    body = _normalize_inline_metadata(body)
    from .vensim_macros import expand_vensim_macros

    body = expand_vensim_macros(body)
    body = re.sub(
        r"(?ms)^[ \t]*\*{3,}[ \t]*\r?\n[ \t]*\.Control[ \t]*\r?\n"
        r"[ \t]*\*{3,}~.*?^[ \t]*\|[ \t]*$",
        "",
        body,
    )
    body, tables, tables_names = _extract_vensim_tables(body)
    from .vensim_subscripts import remove_dimensions

    body = remove_dimensions(body)
    record = re.compile(
        r"(?ms)^(?P<lhs>.+?)\s*=\s*(?P<rhs>.*?)(?=\n[ \t]*~|\Z)"
        r"(?:\n[ \t]*~[ \t]*(?P<units>[^\n]*))?"
        r"(?:\n[ \t]*~[ \t]*(?P<comment>.*?)\|)?"
    )
    raw = []
    controls = {}
    for match in record.finditer(body):
        label = re.sub(r"\\\s*\n\s*", " ", _clean_label(match.group("lhs")))
        rhs = re.sub(r"\\\s*\n\s*", " ", match.group("rhs")).strip()
        if not label or not rhs:
            continue
        units = (match.group("units") or "").strip()
        if label.upper() in _CONTROL_NAMES:
            controls[label.upper()] = (rhs, units)
            continue
        raw.append(
            {
                "label": label,
                "rhs": rhs,
                "units": units,
                "description": (match.group("comment") or "").strip(),
            }
        )
    if not raw:
        raise ModelValidationError("Vensim model contains no equations")
    if any("[" in item["label"] for item in raw):
        from .vensim_subscripts import import_subscripted

        return import_subscripted(raw, controls, tables, tables_names, body, source_name, source)
    used: set[str] = set()
    labels = {item["label"] for item in raw}
    names = {}
    for label in sorted(labels):
        names[label] = identifier(label, used)
        used.add(names[label])
    from .vensim_subscripts import _import_units

    variables = []
    flows = set()
    for item in raw:
        expression = ExpressionParser(item["rhs"], names, tables_names).parse()
        common = {
            "id": names[item["label"]],
            "label": item["label"],
            "description": item["description"] or None,
            "units": _import_units(item["units"]),
            "units_raw": item["units"] or None,
        }
        if expression.op == "call" and expression.name == "integ":
            if len(expression.args) != 2:
                raise ModelValidationError(f"invalid INTEG for {item['label']}")
            variables.append(
                {
                    **common,
                    "kind": "stock",
                    "initial": expression.args[1],
                    "derivative": expression.args[0],
                }
            )
            flows.update(dependencies(expression.args[0]))
        else:
            variables.append({**common, "kind": "auxiliary", "expression": expression})
    for variable in variables:
        if variable["kind"] == "stock":
            continue
        if variable["id"] in flows:
            variable["kind"] = "flow"
            variable["topology_status"] = "missing"
        elif not dependencies(variable["expression"]) and not any(
            node.op == "time"
            or (
                node.op == "call"
                and node.name
                in {
                    "step",
                    "pulse",
                    "pulse_train",
                    "ramp",
                    "delay1",
                    "delay3",
                    "delay1i",
                    "delay3i",
                    "smooth",
                    "smooth3",
                    "smoothi",
                    "smooth3i",
                    "initial",
                }
            )
            for node in _walk(variable["expression"])
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
        provenance={
            "kind": "vensim_import",
            "source_name": source_name,
            "source_sha256": _source_hash(source),
        },
    )
    return _finish(document)


def _walk(expression: Expression):
    from .ir import walk

    return walk(expression)


def _number(value: str) -> float:
    try:
        return float(value.strip())
    except ValueError:
        return 0.0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element if _local(item.tag) == name), None)


def _text(element: ET.Element, name: str, default: str = "") -> str:
    child = _child(element, name)
    return (child.text or "").strip() if child is not None else default


def _points(text: str) -> list[float]:
    if not text.strip():
        return []
    try:
        return [float(item.strip()) for item in text.split(",") if item.strip()]
    except ValueError as exc:
        raise ModelValidationError("invalid lookup points") from exc


def import_xmile(source: str, *, source_name: str = "model.xmile") -> ModelDocument:
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", source, re.IGNORECASE):
        raise ModelValidationError("DTD and external entities are not allowed")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise ModelValidationError(f"invalid XMILE XML: {exc}") from exc
    variables_node = next((item for item in root.iter() if _local(item.tag) == "variables"), None)
    if variables_node is None:
        raise ModelValidationError("XMILE model has no variables")
    elements = [
        item for item in variables_node if _local(item.tag) in {"stock", "flow", "aux", "gf"}
    ]
    labels = [item.attrib.get("name", "") for item in elements]
    used: set[str] = set()
    names = {}
    for label in labels:
        if label.upper() in _CONTROL_NAMES:
            continue
        names[label] = identifier(label, used)
        used.add(names[label])
    table_names = {
        label: identifier(label, set())
        for label in labels
        if any(
            item.attrib.get("name") == label
            and (_local(item.tag) == "gf" or _child(item, "gf") is not None)
            for item in elements
        )
    }
    tables = []
    raw = []
    for element in elements:
        kind = _local(element.tag)
        label = element.attrib.get("name", "")
        if label.upper() in _CONTROL_NAMES:
            continue
        gf = element if kind == "gf" else _child(element, "gf")
        if gf is not None:
            xs = _points(_text(gf, "xpts"))
            ys = _points(_text(gf, "ypts"))
            if not xs and _child(gf, "xscale") is not None:
                scale = _child(gf, "xscale")
                xs = [float(scale.attrib["min"]), float(scale.attrib["max"])]
            if len(xs) != len(ys) or len(xs) < 2:
                raise ModelValidationError(f"invalid lookup table: {label}")
            tables.append(
                LookupTable(
                    id=table_names[label],
                    label=label,
                    points=list(zip(xs, ys, strict=True)),
                    y_units=parse_units(_text(element, "units")) or None,
                )
            )
            if kind == "gf":
                continue
        equation = _text(element, "eqn")
        if not equation:
            if kind == "stock":
                equation = "0"
            else:
                continue
        expression = ExpressionParser(equation, names, table_names).parse()
        common = {
            "id": names[label],
            "label": label,
            "description": _text(element, "doc") or None,
            "units": parse_units(_text(element, "units")),
            "units_raw": _text(element, "units") or None,
        }
        if kind == "stock":
            inflows = [
                _clean_label(item.text or "") for item in element if _local(item.tag) == "inflow"
            ]
            outflows = [
                _clean_label(item.text or "") for item in element if _local(item.tag) == "outflow"
            ]
            raw.append(
                {
                    **common,
                    "kind": "stock",
                    "initial": expression,
                    "derivative": _stock_derivative(inflows, outflows, names),
                }
            )
        else:
            raw.append(
                {
                    **common,
                    "kind": kind if kind == "flow" else "auxiliary",
                    "expression": expression,
                }
            )
    for variable in raw:
        if variable["kind"] == "flow":
            variable["topology_status"] = "missing"
        elif (
            variable["kind"] == "auxiliary"
            and not dependencies(variable["expression"])
            and not any(
                node.op == "time"
                or (
                    node.op == "call"
                    and node.name
                    in {
                        "step",
                        "pulse",
                        "pulse_train",
                        "ramp",
                        "delay1",
                        "delay3",
                        "delay1i",
                        "delay3i",
                        "smooth",
                        "smooth3",
                        "smoothi",
                        "smooth3i",
                        "initial",
                    }
                )
                for node in _walk(variable["expression"])
            )
        ):
            variable["kind"] = "constant"
    _infer_topology(raw)
    specs = next((item for item in root.iter() if _local(item.tag) == "sim_specs"), None)
    unit = specs.attrib.get("time_units", "time") if specs is not None else "time"
    document = ModelDocument(
        name=Path(source_name).stem,
        description="Imported XMILE model",
        time=TimeSettings(
            unit=parse_units(unit) and next(iter(parse_units(unit))) or unit,
            initial_time=_number(_text(specs, "start", "0") if specs is not None else "0"),
            final_time=_number(_text(specs, "stop", "100") if specs is not None else "100"),
            time_step=_number(_text(specs, "dt", "0.25") if specs is not None else "0.25"),
            saveper=_number(
                _text(specs, "saveper", _text(specs, "dt", "0.25") if specs is not None else "0.25")
                if specs is not None
                else "0.25"
            ),
        ),
        variables=raw,
        tables=tables,
        provenance={
            "kind": "xmile_import",
            "source_name": source_name,
            "source_sha256": _source_hash(source),
        },
    )
    return _finish(document)


def export_xmile(document: ModelDocument) -> str:
    if document.dimensions or any(item.subscripts for item in document.variables):
        raise ModelValidationError(
            "UNSUPPORTED_CAPABILITY: subscripted XMILE export is not implemented yet"
        )
    namespace = "http://docs.oasis-open.org/xmile/ns/XMILE/v1.0"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}xmile", {"version": "1.0"})
    header = ET.SubElement(root, f"{{{namespace}}}header")
    ET.SubElement(header, f"{{{namespace}}}name").text = document.name
    specs = ET.SubElement(
        root, f"{{{namespace}}}sim_specs", {"method": "Euler", "time_units": document.time.unit}
    )
    for tag, value in (
        ("start", document.time.initial_time),
        ("stop", document.time.final_time),
        ("dt", document.time.time_step),
        ("saveper", document.time.saveper),
    ):
        ET.SubElement(specs, f"{{{namespace}}}{tag}").text = repr(value)
    model = ET.SubElement(root, f"{{{namespace}}}model")
    variables = ET.SubElement(model, f"{{{namespace}}}variables")
    names = {item.id: item.label or item.id for item in document.variables}
    table_names = {item.id: item.label or item.id for item in document.tables}
    for table in document.tables:
        gf = ET.SubElement(
            variables, f"{{{namespace}}}gf", {"name": table.label or table.id, "type": "continuous"}
        )
        ET.SubElement(gf, f"{{{namespace}}}xpts").text = ",".join(
            repr(point[0]) for point in table.points
        )
        ET.SubElement(gf, f"{{{namespace}}}ypts").text = ",".join(
            repr(point[1]) for point in table.points
        )
    for variable in document.variables:
        element = ET.SubElement(
            variables,
            f"{{{namespace}}}{'aux' if variable.kind in {'auxiliary', 'constant'} else variable.kind}",
            {"name": variable.label or variable.id},
        )
        if variable.description:
            ET.SubElement(element, f"{{{namespace}}}doc").text = variable.description
        if variable.units is not None or variable.units_raw:
            ET.SubElement(element, f"{{{namespace}}}units").text = format_units(
                variable.units, variable.units_raw
            )
        if variable.kind == "stock":
            ET.SubElement(element, f"{{{namespace}}}eqn").text = _expression_to_xmile(
                variable.initial, names, table_names
            )
            for flow in document.variables:
                if flow.kind != "flow":
                    continue
                if flow.target and flow.target.kind == "stock" and flow.target.id == variable.id:
                    ET.SubElement(element, f"{{{namespace}}}inflow").text = flow.label or flow.id
                if flow.source and flow.source.kind == "stock" and flow.source.id == variable.id:
                    ET.SubElement(element, f"{{{namespace}}}outflow").text = flow.label or flow.id
        else:
            ET.SubElement(element, f"{{{namespace}}}eqn").text = _expression_to_xmile(
                variable.expression, names, table_names
            )
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _expression_to_xmile(expression: Expression, names: dict[str, str], tables: dict[str, str]) -> str:
    rendered = expression_to_vensim(expression, names, tables)
    for name in ("delay1i", "delay3i", "smoothi", "smooth3i"):
        rendered = re.sub(rf"\b{name.upper()}\(", f"{name[:-1].upper()}(", rendered)
    return rendered


def import_model(source: str, file_format: str, *, source_name: str) -> ModelDocument:
    if file_format == "vensim":
        return import_vensim(source, source_name=source_name)
    if file_format == "xmile":
        return import_xmile(source, source_name=source_name)
    raise ModelValidationError(f"unsupported import format: {file_format}")


def export_csv(result: SimulationResult) -> str:
    output = io.StringIO()
    names = list(result.variables)
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["time", *names])
    for index, value in enumerate(result.time):
        writer.writerow([value, *[result.variables[name][index] for name in names]])
    return output.getvalue()

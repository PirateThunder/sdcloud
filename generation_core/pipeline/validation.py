from __future__ import annotations

import networkx as nx

from .exceptions import ModelValidationError
from .ir import (
    FUNCTION_SIGNATURES,
    constant_number,
    derivative_for,
    model_capabilities,
    walk,
    with_derivatives,
)
from .schemas import (
    ArrayExpression,
    BinaryExpression,
    BooleanExpression,
    CallExpression,
    CompareExpression,
    Expression,
    IfExpression,
    IndexedExpression,
    LiteralExpression,
    LookupExpression,
    ModelDocument,
    ReferenceExpression,
    TimeExpression,
    UnaryExpression,
    ValidationIssue,
    ValidationReport,
)
from .units import combine

_UNKNOWN = object()
_RESERVED = {"time", "np", "min", "max", "abs", "integ", *FUNCTION_SIGNATURES}


class ModelValidator:
    def __init__(self, document: ModelDocument) -> None:
        self.document = document
        self.issues: list[ValidationIssue] = []
        self.variables = {item.id: item for item in document.variables}
        self.tables = {item.id: item for item in document.tables}
        self.generated = document.provenance.kind == "text_generation"

    def issue(self, code: str, path: str, message: str, *, severity: str | None = None) -> None:
        self.issues.append(
            ValidationIssue(
                code=code,
                severity=severity or ("error" if self.generated else "warning"),
                path=path,
                message=message,
            )
        )

    def error(self, code: str, path: str, message: str) -> None:
        self.issue(code, path, message, severity="error")

    def validate(self) -> ValidationReport:
        ids = [item.id for item in self.document.variables]
        if len(ids) != len(set(ids)):
            self.error("DUPLICATE_VARIABLE", "variables", "variable ids must be unique")
        reserved = set(ids) & _RESERVED
        if reserved:
            self.error("RESERVED_VARIABLE", "variables", f"reserved ids: {sorted(reserved)}")
        if len(self.tables) != len(self.document.tables):
            self.error("DUPLICATE_TABLE", "tables", "lookup table ids must be unique")
        if not any(item.kind == "stock" for item in self.document.variables):
            self.error("STOCK_REQUIRED", "variables", "model must contain at least one stock")
        self._validate_dimensions()
        for variable in self.document.variables:
            path = f"variables.{variable.id}"
            if variable.units is None:
                self.issue(
                    "UNITS_UNKNOWN",
                    f"{path}.units",
                    "units are not declared or could not be parsed",
                )
            for expression in self._expressions(variable):
                self._validate_expression(expression, path)
            if variable.kind == "constant":
                refs = {
                    node.name
                    for node in walk(variable.expression)
                    if isinstance(node, ReferenceExpression)
                }
                if (
                    any(isinstance(node, TimeExpression) for node in walk(variable.expression))
                    or any(
                        isinstance(node, CallExpression)
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
                        for node in walk(variable.expression)
                    )
                    or any(
                        self.variables.get(name) and self.variables[name].kind != "constant"
                        for name in refs
                    )
                ):
                    self.error(
                        "DYNAMIC_CONSTANT",
                        path,
                        "constant cannot depend on time or runtime variables",
                    )
            if variable.kind == "stock":
                self._validate_stock(variable)
                self._check_expression_units(variable.initial, variable.units, f"{path}.initial")
                if variable.derivative is not None:
                    self._check_expression_units(
                        variable.derivative,
                        combine(variable.units or {}, {self.document.time.unit: -1})
                        if variable.units is not None
                        else None,
                        f"{path}.derivative",
                    )
            else:
                self._check_expression_units(
                    variable.expression, variable.units, f"{path}.expression"
                )
        self._validate_flows()
        self._validate_auxiliary_cycles()
        status = (
            "failed"
            if any(item.severity == "error" for item in self.issues)
            else ("passed_with_warnings" if self.issues else "passed")
        )
        return ValidationReport(
            status=status,
            issues=self.issues,
            capabilities=self._capabilities(),
        )

    def _expressions(self, variable):
        if hasattr(variable, "expression"):
            yield variable.expression
        if hasattr(variable, "initial"):
            yield variable.initial
        if getattr(variable, "derivative", None) is not None:
            yield variable.derivative

    def _validate_expression(self, expression: Expression, path: str) -> None:
        nodes = list(walk(expression))
        if len(nodes) > 500:
            self.error("EXPRESSION_TOO_LARGE", path, "expression has more than 500 AST nodes")
        for node in nodes:
            if (
                isinstance(node, ReferenceExpression | IndexedExpression)
                and node.name not in self.variables
            ):
                self.error("UNKNOWN_REFERENCE", path, f"unknown variable reference: {node.name}")
            if isinstance(node, LookupExpression) and node.table not in self.tables:
                self.error("UNKNOWN_LOOKUP", path, f"unknown lookup table: {node.table}")
            if isinstance(node, CallExpression):
                signature = FUNCTION_SIGNATURES.get(node.name)
                if signature is None:
                    self.error("UNKNOWN_FUNCTION", path, f"function is not allowed: {node.name}")
                elif not signature[0] <= len(node.args) <= signature[1]:
                    self.error(
                        "INVALID_FUNCTION_ARITY",
                        path,
                        f"{node.name} expects {signature[0]}..{signature[1]} arguments",
                    )
        self._shape(expression, path)

    def _validate_dimensions(self) -> None:
        dimensions = {item.id: item for item in self.document.dimensions}
        if len(dimensions) != len(self.document.dimensions):
            self.error("DUPLICATE_DIMENSION", "dimensions", "dimension ids must be unique")
        for dimension in self.document.dimensions:
            if len(dimension.elements) != len(set(dimension.elements)):
                self.error(
                    "DUPLICATE_ELEMENT",
                    f"dimensions.{dimension.id}",
                    "dimension elements must be unique",
                )
        for variable in self.document.variables:
            path = f"variables.{variable.id}"
            if len(variable.subscripts) != len(set(variable.subscripts)):
                self.error("DUPLICATE_SUBSCRIPT", path, "variable subscripts must be unique")
            for name in variable.subscripts:
                if name not in dimensions:
                    self.error("UNKNOWN_SUBSCRIPT", path, f"unknown dimension: {name}")
            expected = 1
            for name in variable.subscripts:
                if name in dimensions:
                    expected *= len(dimensions[name].elements)
            for expression in self._expressions(variable):
                for node in walk(expression):
                    if isinstance(node, ArrayExpression):
                        if not variable.subscripts:
                            self.error(
                                "UNEXPECTED_ARRAY",
                                path,
                                "array literal requires variable subscripts",
                            )
                        elif len(node.values) != expected:
                            self.error(
                                "ARRAY_LENGTH_MISMATCH",
                                path,
                                f"array has {len(node.values)} values; expected {expected}",
                            )
                        if len(variable.subscripts) > 1 and not node.shape:
                            self.error(
                                "ARRAY_SHAPE_REQUIRED",
                                path,
                                "multidimensional arrays require shape",
                            )
                        if node.shape:
                            shape_size = 1
                            for size in node.shape:
                                shape_size *= size
                            if (
                                len(node.shape) != len(variable.subscripts)
                                or shape_size != expected
                                or any(size < 1 for size in node.shape)
                            ):
                                self.error(
                                    "ARRAY_SHAPE_MISMATCH",
                                    path,
                                    "array shape does not match variable dimensions",
                                )

    def _shape(self, expression: Expression, path: str) -> list[str] | None:
        if isinstance(expression, LiteralExpression):
            return []
        if isinstance(expression, ReferenceExpression):
            variable = self.variables.get(expression.name)
            return list(variable.subscripts) if variable else []
        if isinstance(expression, IndexedExpression):
            variable = self.variables.get(expression.name)
            if variable is None:
                return []
            dimensions = {item.id: item.elements for item in self.document.dimensions}
            for dimension, element in expression.indices.items():
                if dimension not in variable.subscripts:
                    self.error(
                        "UNKNOWN_SUBSCRIPT",
                        path,
                        f"{dimension} is not a subscript of {variable.id}",
                    )
                elif element != "*" and element not in dimensions.get(dimension, []):
                    self.error("UNKNOWN_ELEMENT", path, f"unknown element {element} in {dimension}")
            return [name for name in variable.subscripts if expression.indices.get(name) == "*"]
        if isinstance(expression, ArrayExpression):
            return None
        if isinstance(expression, TimeExpression | CompareExpression | BooleanExpression):
            return []
        if isinstance(expression, UnaryExpression):
            return self._shape(expression.arg, path)
        if isinstance(expression, BinaryExpression):
            left = self._shape(expression.args[0], path)
            right = self._shape(expression.args[1], path)
            if left is None or right is None:
                return None
            if left and right and left != right:
                self.error(
                    "INCOMPATIBLE_DIMENSIONS", path, f"incompatible dimensions: {left} and {right}"
                )
                return []
            return left or right
        if isinstance(expression, LookupExpression):
            return self._shape(expression.arg, path)
        if isinstance(expression, IfExpression):
            then = self._shape(expression.then, path)
            otherwise = self._shape(expression.otherwise, path)
            if then is None or otherwise is None:
                return None
            if then and otherwise and then != otherwise:
                self.error(
                    "INCOMPATIBLE_DIMENSIONS",
                    path,
                    "conditional branches have different dimensions",
                )
                return []
            return then or otherwise
        if isinstance(expression, CallExpression):
            if expression.name in {"sum", "prod", "vmin", "vmax"}:
                return []
            return self._shape(expression.args[0], path) if expression.args else []
        return []

    def _validate_stock(self, stock) -> None:
        path = f"variables.{stock.id}"
        initial_refs = {
            node.name for node in walk(stock.initial) if isinstance(node, ReferenceExpression)
        }
        if any(isinstance(node, TimeExpression) for node in walk(stock.initial)) or any(
            self.variables.get(name) and self.variables[name].kind != "constant"
            for name in initial_refs
        ):
            self.error("INVALID_INITIAL", f"{path}.initial", "stock initial must be constant")
        if stock.derivative is None and not stock.allow_isolated:
            self.error("UNCONNECTED_STOCK", path, "stock has no incoming or outgoing flow")
        for flow in self.document.variables:
            if flow.kind != "flow":
                continue
            endpoints = [flow.source, flow.target]
            connected = [
                endpoint
                for endpoint in endpoints
                if endpoint and endpoint.kind == "stock" and endpoint.id == stock.id
            ]
            if not connected:
                continue
            if flow.source is None or flow.target is None:
                self.issue(
                    "TOPOLOGY_MISSING", f"variables.{flow.id}", "flow topology is incomplete"
                )
            elif flow.source == flow.target:
                self.error(
                    "INVALID_FLOW", f"variables.{flow.id}", "flow source and target coincide"
                )
        if stock.derivative is not None:
            expected = self._topology_derivative(stock.id)
            if expected is not None and stock.derivative != expected:
                self.error(
                    "DERIVATIVE_TOPOLOGY_MISMATCH",
                    f"{path}.derivative",
                    "stock derivative does not match flow topology",
                )

    def _topology_derivative(self, stock_id: str) -> Expression | None:
        without_derivative = self.document.model_copy(
            update={
                "variables": [
                    item.model_copy(update={"derivative": None})
                    if item.id == stock_id and item.kind == "stock"
                    else item
                    for item in self.document.variables
                ]
            }
        )
        return derivative_for(without_derivative, stock_id)

    def _validate_flows(self) -> None:
        stocks = {item.id: item for item in self.document.variables if item.kind == "stock"}
        for flow in (item for item in self.document.variables if item.kind == "flow"):
            path = f"variables.{flow.id}"
            if flow.source is None or flow.target is None:
                self.issue("TOPOLOGY_MISSING", path, "flow must declare source and target")
                continue
            if flow.source == flow.target:
                self.error("INVALID_FLOW", path, "flow source and target coincide")
            if flow.source.kind == "cloud" and flow.target.kind == "cloud":
                self.error("FLOW_WITHOUT_STOCK", path, "flow must connect at least one stock")
            for endpoint in (flow.source, flow.target):
                if endpoint.kind == "stock" and endpoint.id not in stocks:
                    self.error("UNKNOWN_STOCK", path, f"unknown stock endpoint: {endpoint.id}")
                if endpoint.kind == "cloud" and endpoint.id in self.variables:
                    self.error(
                        "CLOUD_VARIABLE_COLLISION",
                        path,
                        f"cloud id collides with a variable: {endpoint.id}",
                    )
            for endpoint in (flow.source, flow.target):
                if endpoint.kind != "stock" or endpoint.id not in stocks:
                    continue
                stock = stocks[endpoint.id]
                if flow.units is not None and stock.units is not None:
                    expected = combine(stock.units, {self.document.time.unit: -1})
                    if flow.units != expected:
                        self.issue(
                            "INCOMPATIBLE_UNITS",
                            f"{path}.units",
                            f"flow units {flow.units} do not match {expected}",
                        )

    def _validate_auxiliary_cycles(self) -> None:
        graph = nx.DiGraph()
        graph.add_nodes_from(self.variables)
        for variable in self.document.variables:
            if variable.kind not in {"auxiliary", "constant"}:
                continue
            for node in walk(variable.expression):
                if isinstance(node, ReferenceExpression):
                    graph.add_edge(node.name, variable.id)
        for cycle in nx.simple_cycles(graph):
            if all(self.variables[name].kind in {"auxiliary", "constant"} for name in cycle):
                self.error("AUXILIARY_CYCLE", "variables", f"algebraic cycle: {' -> '.join(cycle)}")

    def _check_expression_units(self, expression: Expression, declared, path: str) -> None:
        if isinstance(expression, LiteralExpression):
            return
        inferred = self._units(expression, path)
        if inferred is _UNKNOWN or declared is None or inferred is None:
            return
        if inferred != declared:
            self.issue(
                "INCOMPATIBLE_UNITS",
                path,
                f"expression units {inferred} do not match declared units {declared}",
            )

    def _units(self, expression: Expression, path: str):
        if isinstance(expression, LiteralExpression):
            return {}
        if isinstance(expression, ReferenceExpression):
            variable = self.variables.get(expression.name)
            return _UNKNOWN if variable is None or variable.units is None else variable.units
        if isinstance(expression, TimeExpression):
            return {self.document.time.unit: 1}
        if isinstance(expression, UnaryExpression):
            return {} if expression.op == "not" else self._units(expression.arg, path)
        if isinstance(expression, CompareExpression):
            left, right = (self._units(item, path) for item in expression.args)
            time_units = {self.document.time.unit: 1}
            numeric_time = (left == time_units and right == {}) or (
                right == time_units and left == {}
            )
            if (
                left is not _UNKNOWN
                and right is not _UNKNOWN
                and left != right
                and not numeric_time
            ):
                self.issue("INCOMPATIBLE_UNITS", path, "comparison operands have different units")
            return {}
        if isinstance(expression, BooleanExpression):
            return {}
        if isinstance(expression, BinaryExpression):
            left, right = (self._units(item, path) for item in expression.args)
            if left is _UNKNOWN or right is _UNKNOWN:
                return _UNKNOWN
            if expression.op in {"add", "sub", "mod"}:
                if left != right:
                    self.issue(
                        "INCOMPATIBLE_UNITS",
                        path,
                        f"{expression.op} operands have different units: "
                        f"left={left}, right={right}",
                    )
                    return _UNKNOWN
                return left
            if expression.op == "mul":
                return combine(left, right)
            if expression.op == "div":
                return combine(left, right, -1)
            exponent = constant_number(expression.args[1])
            if exponent is None or int(exponent) != exponent:
                return _UNKNOWN
            return {name: power * int(exponent) for name, power in left.items() if power}
        if isinstance(expression, LookupExpression):
            table = self.tables.get(expression.table)
            return _UNKNOWN if table is None or table.y_units is None else table.y_units
        if isinstance(expression, IfExpression):
            then = self._units(expression.then, path)
            otherwise = self._units(expression.otherwise, path)
            if then is _UNKNOWN or otherwise is _UNKNOWN:
                return _UNKNOWN
            if then != otherwise:
                self.issue("INCOMPATIBLE_UNITS", path, "conditional branches have different units")
                return _UNKNOWN
            return then
        if isinstance(expression, CallExpression):
            return self._call_units(expression, path)
        return _UNKNOWN

    def _call_units(self, expression: CallExpression, path: str):
        args = [self._units(item, path) for item in expression.args]
        name = expression.name
        if name in {"min", "max", "minimum", "maximum", "abs"}:
            known = [item for item in args if item is not _UNKNOWN]
            if known and any(item != known[0] for item in known[1:]):
                self.issue(
                    "INCOMPATIBLE_UNITS",
                    path,
                    f"{name} arguments have different units: {args}",
                )
                return _UNKNOWN
            return known[0] if known else _UNKNOWN
        if name in {"exp", "log", "log10", "sin", "cos", "tan"}:
            if args and args[0] is not _UNKNOWN and args[0] != {}:
                self.issue(
                    "DIMENSIONED_TRANSCENDENTAL", path, f"{name} expects a dimensionless argument"
                )
            return {}
        if name in {"sqrt", "floor", "ceil", "round"}:
            if (
                name == "sqrt"
                and args
                and args[0] is not _UNKNOWN
                and any(power % 2 for power in args[0].values())
            ):
                self.issue("INVALID_SQRT_UNITS", path, "sqrt requires even unit exponents")
                return _UNKNOWN
            if name == "sqrt":
                return (
                    {key: power // 2 for key, power in args[0].items()}
                    if args[0] is not _UNKNOWN
                    else _UNKNOWN
                )
            return args[0] if args else _UNKNOWN
        if name == "power":
            if len(args) == 2 and args[1] is not _UNKNOWN and args[1] != {}:
                self.issue("DIMENSIONED_EXPONENT", path, "power exponent must be dimensionless")
            return args[0] if args else _UNKNOWN
        if name in {"xidz", "zidz"}:
            if len(args) >= 2 and args[0] is not _UNKNOWN and args[1] is not _UNKNOWN:
                return combine(args[0], args[1], -1)
            return _UNKNOWN
        if name == "if_then_else" and len(args) == 3:
            return args[1] if args[1] == args[2] else _UNKNOWN
        if name in {
            "delay1",
            "delay3",
            "delay1i",
            "delay3i",
            "smooth",
            "smooth3",
            "smoothi",
            "smooth3i",
            "initial",
        }:
            return args[0] if args else _UNKNOWN
        return _UNKNOWN

    def _capabilities(self):
        capabilities = set(self.document.capabilities or model_capabilities(self.document))
        stateful = capabilities & {"delay", "smooth", "initial", "events", "subscripts"}
        stock_without_topology = [
            item.id
            for item in self.document.variables
            if item.kind == "stock"
            and item.derivative is not None
            and not any(
                flow.kind == "flow"
                and (
                    (flow.source and flow.source.kind == "stock" and flow.source.id == item.id)
                    or (flow.target and flow.target.kind == "stock" and flow.target.id == item.id)
                )
                for flow in self.document.variables
            )
        ]
        supported = {
            "pysd_euler": True,
            "scipy_fixed": not stateful,
            "scipy_adaptive": not stateful,
            "vensim_export": True,
            "xmile_export": not stock_without_topology and "subscripts" not in capabilities,
        }
        reasons = {}
        if "subscripts" in capabilities:
            reasons["xmile_export"] = ["subscripted XMILE export is not implemented yet"]
        if stateful:
            reasons["scipy_fixed"] = [f"unsupported stateful features: {sorted(stateful)}"]
            reasons["scipy_adaptive"] = [f"unsupported stateful features: {sorted(stateful)}"]
        if stock_without_topology:
            reasons["xmile_export"] = [
                f"missing flow topology for stocks: {stock_without_topology}"
            ]
        return {"supported": supported, "reasons": reasons}


def validate_model(document: ModelDocument) -> ValidationReport:
    return ModelValidator(with_derivatives(document)).validate()


def finalize_model(document: ModelDocument) -> ModelDocument:
    from .graphs import build_graphs

    normalized = with_derivatives(document)
    report = validate_model(normalized)
    capabilities = model_capabilities(normalized)
    normalized = normalized.model_copy(update={"validation": report, "capabilities": capabilities})
    cld, sfd = build_graphs(normalized)
    return normalized.model_copy(update={"cld_data": cld, "sfd_data": sfd})


def ensure_valid_model(document: ModelDocument) -> ModelDocument:
    finalized = finalize_model(document)
    errors = [item for item in finalized.validation.issues if item.severity == "error"]
    if errors:
        summary = "; ".join(f"{item.code} at {item.path}: {item.message}" for item in errors[:10])
        raise ModelValidationError(summary)
    return finalized

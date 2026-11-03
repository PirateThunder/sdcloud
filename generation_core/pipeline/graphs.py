from __future__ import annotations

from itertools import islice

import networkx as nx

from .ir import constant_number, dependencies
from .schemas import (
    BinaryExpression,
    CLDData,
    CLDEdge,
    CLDNode,
    Expression,
    FeedbackLoop,
    GraphValidation,
    ModelDocument,
    ReferenceExpression,
    SFDData,
    SFDEdge,
    SFDNode,
    UnaryExpression,
)


def _cycles(graph: nx.DiGraph) -> list[FeedbackLoop]:
    loops = []
    for cycle in islice(nx.simple_cycles(graph, length_bound=20), 100):
        polarities = [
            graph.edges[source, cycle[(index + 1) % len(cycle)]].get("polarity")
            for index, source in enumerate(cycle)
        ]
        if "unknown" in polarities:
            continue
        polarity = "-" if polarities.count("-") % 2 else "+"
        loops.append(
            FeedbackLoop(
                nodes=cycle,
                length=len(cycle),
                polarity=polarity,
                type="reinforcing" if polarity == "+" else "balancing",
            )
        )
    return loops


def validate_cld(nodes: list[CLDNode], edges: list[CLDEdge]) -> GraphValidation:
    issues: list[str] = []
    graph = nx.DiGraph()
    ids = [node.id for node in nodes]
    graph.add_nodes_from(ids)
    if not nodes:
        issues.append("error: CLD has no nodes")
    if len(ids) != len(set(ids)):
        issues.append("error: duplicate CLD node ids")
    known = set(ids)
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            issues.append(f"error: edge references unknown node: {edge.source} -> {edge.target}")
        else:
            graph.add_edge(edge.source, edge.target, polarity=edge.polarity)
    isolated = [node for node in graph if graph.degree(node) == 0]
    if isolated:
        issues.append(f"warning: isolated nodes: {isolated}")
    if graph.number_of_nodes() and not nx.is_weakly_connected(graph):
        issues.append("warning: CLD is not weakly connected")
    loops = _cycles(graph)
    truncated = nx.number_of_nodes(graph) > 0 and len(loops) >= 100
    if not loops:
        issues.append("warning: no feedback loops with known polarity detected")
    return GraphValidation(
        valid=not any(item.startswith("error:") for item in issues),
        issues=issues,
        feedback_loops=loops,
        metrics={
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "feedback_loop_count": len(loops),
            "loops_truncated": truncated,
        },
    )


def validate_sfd(
    nodes: list[SFDNode],
    edges: list[SFDEdge],
    *,
    allow_isolated_stocks: set[str] | None = None,
) -> GraphValidation:
    issues: list[str] = []
    graph = nx.DiGraph()
    ids = [node.id for node in nodes]
    graph.add_nodes_from(ids)
    known = set(ids)
    types = {node.id: node.type for node in nodes}
    if not nodes:
        issues.append("error: SFD has no nodes")
    if len(ids) != len(known):
        issues.append("error: duplicate SFD node ids")
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            issues.append(f"error: unknown SFD edge: {edge.source} -> {edge.target}")
            continue
        graph.add_edge(edge.source, edge.target, type=edge.type)
        if edge.type == "flow":
            source_type = types[edge.source]
            target_type = types[edge.target]
            if source_type == "flow" and target_type not in {"stock", "cloud"}:
                issues.append(f"error: invalid flow target: {edge.source} -> {edge.target}")
            if target_type == "flow" and source_type not in {"stock", "cloud"}:
                issues.append(f"error: invalid flow source: {edge.source} -> {edge.target}")
            if source_type != "flow" and target_type != "flow":
                issues.append(
                    f"error: material edge does not contain a flow: {edge.source} -> {edge.target}"
                )
    for stock in (node for node in nodes if node.type == "stock"):
        neighbors = set(graph.predecessors(stock.id)) | set(graph.successors(stock.id))
        flows = {
            neighbor
            for neighbor in neighbors
            if types.get(neighbor) == "flow"
            and any(
                edge.type == "flow" and {edge.source, edge.target} == {stock.id, neighbor}
                for edge in edges
            )
        }
        if not flows and stock.id not in (allow_isolated_stocks or set()):
            issues.append(f"error: stock {stock.id} is not connected to a flow")
    for flow in (node for node in nodes if node.type == "flow"):
        incoming = [edge for edge in edges if edge.target == flow.id and edge.type == "flow"]
        outgoing = [edge for edge in edges if edge.source == flow.id and edge.type == "flow"]
        if len(incoming) != 1 or len(outgoing) != 1:
            issues.append(f"error: flow {flow.id} must have one material source and target")
    isolated = [node for node in graph if graph.degree(node) == 0]
    if isolated:
        issues.append(f"warning: isolated SFD nodes: {isolated}")
    return GraphValidation(
        valid=not any(item.startswith("error:") for item in issues),
        issues=issues,
        metrics={
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "stock_count": sum(node.type == "stock" for node in nodes),
            "flow_count": sum(node.type == "flow" for node in nodes),
        },
    )


def _known_number(
    expression: Expression, variables: dict, seen: set[str] | None = None
) -> float | None:
    if isinstance(expression, ReferenceExpression):
        variable = variables.get(expression.name)
        if variable is None or variable.kind != "constant" or expression.name in (seen or set()):
            return None
        return _known_number(variable.expression, variables, (seen or set()) | {expression.name})
    return constant_number(expression)


def _polarity(expression: Expression, reference: str, variables: dict) -> str:
    if isinstance(expression, ReferenceExpression):
        return "+" if expression.name == reference else "unknown"
    if isinstance(expression, UnaryExpression):
        value = _polarity(expression.arg, reference, variables)
        if value == "unknown":
            return value
        if expression.op == "neg":
            return "-" if value == "+" else "+"
        return value
    if isinstance(expression, BinaryExpression):
        if reference not in dependencies(expression):
            return "unknown"
        if expression.op == "add":
            return (
                _polarity(expression.args[0], reference, variables)
                if reference in dependencies(expression.args[0])
                else _polarity(expression.args[1], reference, variables)
            )
        if expression.op == "sub":
            if reference in dependencies(expression.args[1]):
                value = _polarity(expression.args[1], reference, variables)
                return "-" if value == "+" else "+" if value == "-" else "unknown"
            return _polarity(expression.args[0], reference, variables)
        if expression.op in {"mul", "div"}:
            direct = (
                expression.args[0]
                if reference in dependencies(expression.args[0])
                else expression.args[1]
            )
            other = expression.args[1] if direct == expression.args[0] else expression.args[0]
            factor = _known_number(other, variables)
            if factor is None or factor == 0:
                return "unknown"
            value = _polarity(direct, reference, variables)
            invert = factor < 0 or (expression.op == "div" and direct == expression.args[1])
            return (
                ("-" if value == "+" else "+" if value == "-" else "unknown") if invert else value
            )
    return "unknown"


def _add_edge(
    edges: dict[tuple[str, str], CLDEdge], source: str, target: str, polarity: str
) -> None:
    key = (source, target)
    if key in edges and edges[key].polarity != polarity:
        edges[key].polarity = "unknown"
    else:
        edges[key] = CLDEdge(source=source, target=target, polarity=polarity)


def build_graphs(document: ModelDocument) -> tuple[CLDData, SFDData]:
    variables = {item.id: item for item in document.variables}
    cld_nodes = [
        CLDNode(id=item.id, label=item.label or item.id, type=item.type)
        for item in document.variables
    ]
    cld_edges: dict[tuple[str, str], CLDEdge] = {}
    sfd_nodes = [
        SFDNode(id=item.id, label=item.label or item.id, type=item.type)
        for item in document.variables
    ]
    sfd_edges: dict[tuple[str, str, str], SFDEdge] = {}
    for variable in document.variables:
        if variable.kind in {"flow", "auxiliary", "constant"}:
            for dependency in dependencies(variable.expression):
                if dependency == variable.id:
                    continue
                _add_edge(
                    cld_edges,
                    dependency,
                    variable.id,
                    _polarity(variable.expression, dependency, variables),
                )
                if variable.kind != "constant":
                    sfd_edges[(dependency, variable.id, "link")] = SFDEdge(
                        source=dependency, target=variable.id, type="link"
                    )
        if variable.kind == "stock" and variable.derivative is not None:
            for dependency in dependencies(variable.derivative):
                if dependency == variable.id:
                    continue
                _add_edge(
                    cld_edges,
                    dependency,
                    variable.id,
                    _polarity(variable.derivative, dependency, variables),
                )
        if variable.kind != "flow":
            continue
        for endpoint, direction in ((variable.source, "source"), (variable.target, "target")):
            if endpoint is None:
                continue
            if endpoint.kind == "cloud":
                cloud_id = endpoint.id
                sfd_nodes.append(
                    SFDNode(
                        id=cloud_id,
                        label="Source" if direction == "source" else "Sink",
                        type="cloud",
                    )
                )
            if direction == "source":
                edge = SFDEdge(source=endpoint.id, target=variable.id, type="flow")
            else:
                edge = SFDEdge(source=variable.id, target=endpoint.id, type="flow")
            sfd_edges[(edge.source, edge.target, "flow")] = edge
    unique_sfd_nodes = list({node.id: node for node in sfd_nodes}.values())
    allowed_isolated = {
        item.id for item in document.variables if item.kind == "stock" and item.allow_isolated
    }
    return (
        CLDData(
            nodes=cld_nodes,
            edges=list(cld_edges.values()),
            validation=validate_cld(cld_nodes, list(cld_edges.values())),
        ),
        SFDData(
            nodes=unique_sfd_nodes,
            edges=list(sfd_edges.values()),
            validation=validate_sfd(
                unique_sfd_nodes, list(sfd_edges.values()), allow_isolated_stocks=allowed_isolated
            ),
        ),
    )

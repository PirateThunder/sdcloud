"""Graph validation for system dynamics causal loop diagrams and stock-flow diagrams."""

from collections import defaultdict

import networkx as nx

from app.core.exceptions import GraphValidationError


class GraphValidator:
    """Validates system dynamics graphs (CLD and SFD)."""

    def validate_cld(self, nodes: list[dict], edges: list[dict]) -> dict:
        """
        Validate a Causal Loop Diagram.

        Checks:
        - Graph connectivity
        - Presence of feedback loops
        - Edge polarity correctness
        - Isolated nodes

        Returns:
            dict with keys: valid (bool), issues (list), feedback_loops (list),
            metrics (dict)
        """
        issues: list[str] = []
        feedback_loops: list[dict] = []
        metrics: dict = {}

        if not nodes:
            issues.append("CLD has no nodes")
            return {"valid": False, "issues": issues, "feedback_loops": [], "metrics": {}}

        if not edges:
            issues.append("CLD has no edges — feedback loops cannot exist")

        # Build directed graph
        graph = nx.DiGraph()
        node_ids = {n.get("id") for n in nodes if n.get("id")}

        for node in nodes:
            node_id = node.get("id")
            if node_id:
                graph.add_node(node_id, **{k: v for k, v in node.items() if k != "id"})

        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            polarity = edge.get("polarity")
            if src and tgt:
                if src not in node_ids:
                    issues.append(f"Edge references unknown source node: {src}")
                if tgt not in node_ids:
                    issues.append(f"Edge references unknown target node: {tgt}")
                if polarity not in ("+", "-"):
                    issues.append(f"Invalid polarity '{polarity}' for edge {src} -> {tgt}")
                if src in node_ids and tgt in node_ids:
                    graph.add_edge(src, tgt, polarity=polarity)

        # Check for isolated nodes
        if graph.number_of_nodes() > 0:
            isolated = [n for n in graph.nodes() if graph.degree(n) == 0]
            if isolated:
                issues.append(f"Isolated nodes found: {isolated}")

        # Check connectivity
        if graph.number_of_nodes() > 0:
            if not nx.is_weakly_connected(graph):
                components = list(nx.weakly_connected_components(graph))
                issues.append(
                    f"CLD is not connected — {len(components)} weak components found"
                )
                metrics["weak_components"] = len(components)
            else:
                metrics["weak_components"] = 1

        # Find feedback loops
        feedback_loops = self.find_feedback_loops(graph)
        if not feedback_loops:
            issues.append("No feedback loops detected in CLD")

        metrics["node_count"] = graph.number_of_nodes()
        metrics["edge_count"] = graph.number_of_edges()
        metrics["feedback_loop_count"] = len(feedback_loops)

        valid = len([i for i in issues if not i.startswith("CLD has no edges")]) == 0 or (
            len(issues) == 1 and issues[0] == "CLD has no edges — feedback loops cannot exist"
            and len(feedback_loops) == 0
        )
        valid = valid and len([i for i in issues if "not connected" in i]) == 0
        valid = valid and len(feedback_loops) > 0

        return {
            "valid": valid,
            "issues": issues,
            "feedback_loops": feedback_loops,
            "metrics": metrics,
        }

    def validate_sfd(self, nodes: list[dict], edges: list[dict]) -> dict:
        """
        Validate a Stock-Flow Diagram.

        Checks:
        - Every stock is connected to at least one flow
        - No isolated variables
        - Flows connect stocks or clouds
        - Correct structure

        Returns:
            dict with keys: valid (bool), issues (list), metrics (dict)
        """
        issues: list[str] = []
        metrics: dict = {}

        if not nodes:
            issues.append("SFD has no nodes")
            return {"valid": False, "issues": issues, "metrics": {}}

        # Build directed graph
        graph = nx.DiGraph()
        node_ids = set()
        stock_ids = set()
        flow_ids = set()

        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type", "variable")
            if node_id:
                node_ids.add(node_id)
                graph.add_node(node_id, type=node_type, label=node.get("label", node_id))
                if node_type == "stock":
                    stock_ids.add(node_id)
                elif node_type == "flow":
                    flow_ids.add(node_id)

        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            edge_type = edge.get("type", "link")
            if src and tgt:
                if src not in node_ids:
                    issues.append(f"SFD edge references unknown source: {src}")
                if tgt not in node_ids:
                    issues.append(f"SFD edge references unknown target: {tgt}")
                if src in node_ids and tgt in node_ids:
                    graph.add_edge(src, tgt, type=edge_type)

        # Check that every stock has at least one flow connection
        for stock in stock_ids:
            stock_neighbors = set(graph.predecessors(stock)) | set(graph.successors(stock))
            connected_flows = stock_neighbors & flow_ids
            if not connected_flows:
                issues.append(f"Stock '{stock}' is not connected to any flow")

        # Check for isolated nodes
        if graph.number_of_nodes() > 0:
            isolated = [n for n in graph.nodes() if graph.degree(n) == 0]
            if isolated:
                issues.append(f"Isolated SFD nodes: {isolated}")

        # Validate flow connections: flows should connect two stocks or a stock and a cloud
        for flow in flow_ids:
            predecessors = list(graph.predecessors(flow))
            successors = list(graph.successors(flow))
            pred_types = {graph.nodes[p].get("type", "") for p in predecessors}
            succ_types = {graph.nodes[s].get("type", "") for s in successors}
            all_neighbors = predecessors + successors

            if len(all_neighbors) < 2:
                issues.append(
                    f"Flow '{flow}' should connect at least two elements (stocks/clouds)"
                )

        metrics["node_count"] = graph.number_of_nodes()
        metrics["edge_count"] = graph.number_of_edges()
        metrics["stock_count"] = len(stock_ids)
        metrics["flow_count"] = len(flow_ids)

        valid = len(issues) == 0 or all(
            "references unknown" in i for i in issues
        )
        valid = valid and len([i for i in issues if "not connected to any flow" in i]) == 0
        valid = valid and len([i for i in issues if "Isolated" in i]) == 0

        return {
            "valid": valid,
            "issues": issues,
            "metrics": metrics,
        }

    def find_feedback_loops(self, graph: nx.DiGraph) -> list[dict]:
        """
        Find all feedback loops in a directed graph.

        Returns a list of dicts with:
            - nodes: list of node IDs in the loop
            - length: number of edges
            - polarity: '+' for reinforcing, '-' for balancing
        """
        loops: list[dict] = []
        seen: set[tuple] = set()

        try:
            simple_cycles = list(nx.simple_cycles(graph))
        except Exception:
            return loops

        for cycle in simple_cycles:
            # Normalize cycle to start from smallest node for deduplication
            if not cycle:
                continue

            # Create a canonical representation
            min_idx = cycle.index(min(cycle))
            canonical = tuple(cycle[min_idx:] + cycle[:min_idx])
            if canonical in seen:
                continue
            seen.add(canonical)

            # Calculate loop polarity
            polarity = "+"
            for i in range(len(cycle)):
                src = cycle[i]
                tgt = cycle[(i + 1) % len(cycle)]
                if graph.has_edge(src, tgt):
                    edge_polarity = graph.edges[src, tgt].get("polarity", "+")
                    if edge_polarity == "-":
                        polarity = "-" if polarity == "+" else "+"

            loop_type = "reinforcing" if polarity == "+" else "balancing"

            loops.append({
                "nodes": list(canonical),
                "length": len(cycle),
                "polarity": polarity,
                "type": loop_type,
            })

        # Sort by length
        loops.sort(key=lambda x: x["length"])
        return loops

    def validate_model_consistency(
        self,
        variables: list[dict],
        equations: list[dict],
        cld_nodes: list[dict],
        cld_edges: list[dict],
    ) -> dict:
        """
        Validate consistency across variables, equations, and CLD.

        Checks that:
        - Every variable has an equation
        - Every CLD node corresponds to a variable
        - No undefined variables in equations
        """
        issues: list[str] = []

        var_names = {v.get("name") for v in variables if v.get("name")}
        eq_lhs = {e.get("lhs") for e in equations if e.get("lhs")}
        cld_node_names = {n.get("id") for n in cld_nodes if n.get("id")}

        # Variables without equations
        vars_without_eqs = var_names - eq_lhs
        if vars_without_eqs:
            issues.append(f"Variables without equations: {sorted(vars_without_eqs)}")

        # Equations for undefined variables
        eqs_without_vars = eq_lhs - var_names
        if eqs_without_vars:
            issues.append(f"Equations for undefined variables: {sorted(eqs_without_vars)}")

        # CLD nodes not in variables
        cld_not_in_vars = cld_node_names - var_names
        if cld_not_in_vars:
            issues.append(f"CLD nodes not in variables: {sorted(cld_not_in_vars)}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "variable_count": len(var_names),
            "equation_count": len(eq_lhs),
            "cld_node_count": len(cld_node_names),
        }

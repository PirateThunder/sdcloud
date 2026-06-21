"""Stock-Flow Diagram (SFD) builder service."""

import json

from app.services.llm.openrouter import OpenRouterLLM
from app.services.graph.validator import GraphValidator
from app.utils.sd_prompts import SFD_GENERATION_PROMPT


class SFDBuilder:
    """Builds and validates Stock-Flow Diagrams from equations and variables."""

    def __init__(self, llm: OpenRouterLLM | None = None) -> None:
        self.llm = llm or OpenRouterLLM()
        self.validator = GraphValidator()

    async def build_from_equations(
        self,
        variables: list[dict],
        equations: list[dict],
    ) -> dict:
        """
        Build an SFD from variables and equations.

        Args:
            variables: List of variable dicts.
            equations: List of equation dicts with lhs, rhs, variable_type.

        Returns:
            dict with keys: nodes, edges, valid, issues, metrics
        """
        data_json = json.dumps(
            {"variables": variables, "equations": equations},
            ensure_ascii=False,
            indent=2,
        )
        prompt = SFD_GENERATION_PROMPT.format(data=data_json)

        response = await self.llm.chat_with_json_output(
            prompt=prompt,
            system=(
                "You are a system dynamics expert specializing in stock-flow diagrams. "
                "Stocks represent accumulations (marked with rectangles), "
                "flows represent rates of change (marked with valves), "
                "auxiliaries are circles, and clouds are sources/sinks. "
                "Return only valid JSON."
            ),
            temperature=0.4,
        )

        if isinstance(response, dict):
            nodes = response.get("nodes", [])
            edges = response.get("edges", [])
        else:
            nodes = []
            edges = []

        # Ensure all variables appear as SFD nodes
        existing_ids = {n.get("id") for n in nodes}
        for var in variables:
            if var["name"] not in existing_ids:
                nodes.append({
                    "id": var["name"],
                    "label": var["name"],
                    "type": var.get("type", "auxiliary"),
                })

        # Validate SFD
        validation = self.validator.validate_sfd(nodes, edges)

        return {
            "nodes": nodes,
            "edges": edges,
            **validation,
        }

    def build_from_cld(self, cld_data: dict, variables: list[dict]) -> dict:
        """
        Derive an SFD from a CLD by classifying variables into stocks and flows.

        Args:
            cld_data: CLD with nodes and edges.
            variables: List of variable dicts with type information.

        Returns:
            SFD data dict.
        """
        cld_nodes = cld_data.get("nodes", [])
        cld_edges = cld_data.get("edges", [])

        # Variable type lookup
        var_types = {v["name"]: v.get("type", "auxiliary") for v in variables}

        # Build SFD nodes from CLD nodes, converting types
        sfd_nodes: list[dict] = []
        for node in cld_nodes:
            node_id = node.get("id", node.get("label", ""))
            var_type = var_types.get(node_id, node.get("type", "auxiliary"))

            # Map CLD types to SFD types
            type_mapping = {
                "stock": "stock",
                "flow": "flow",
                "auxiliary": "auxiliary",
                "constant": "constant",
                "variable": "auxiliary",
            }
            sfd_type = type_mapping.get(var_type, "auxiliary")

            sfd_nodes.append({
                "id": node_id,
                "label": node.get("label", node_id),
                "type": sfd_type,
            })

        # Build SFD edges from CLD edges
        sfd_edges: list[dict] = []
        for edge in cld_edges:
            sfd_edges.append({
                "source": edge.get("source"),
                "target": edge.get("target"),
                "type": "link",
            })

        # Add flow edges: flows connect stocks
        stock_nodes = [n for n in sfd_nodes if n["type"] == "stock"]
        flow_nodes = [n for n in sfd_nodes if n["type"] == "flow"]

        # Connect flows to stocks if not already connected
        for flow in flow_nodes:
            flow_id = flow["id"]
            has_stock_conn = any(
                e["source"] == flow_id or e["target"] == flow_id
                for e in sfd_edges
            )
            if not has_stock_conn and stock_nodes:
                # Connect to first stock
                sfd_edges.append({
                    "source": stock_nodes[0]["id"],
                    "target": flow_id,
                    "type": "flow",
                })

        # Validate
        validation = self.validator.validate_sfd(sfd_nodes, sfd_edges)

        return {
            "nodes": sfd_nodes,
            "edges": sfd_edges,
            **validation,
        }

    async def refine_sfd(self, sfd_data: dict, feedback: str) -> dict:
        """
        Refine an existing SFD based on feedback.

        Args:
            sfd_data: Current SFD with nodes and edges.
            feedback: Human feedback for refinement.

        Returns:
            Refined SFD data.
        """
        sfd_json = json.dumps(sfd_data, ensure_ascii=False, indent=2)
        prompt = (
            f"Refine the following stock-flow diagram based on feedback:\n\n"
            f"Feedback: {feedback}\n\n"
            f"Current SFD:\n{sfd_json}\n\n"
            f"Return the refined SFD as JSON with 'nodes' and 'edges' arrays."
        )

        response = await self.llm.chat_with_json_output(
            prompt=prompt,
            system="You are a system dynamics expert. Refine SFDs based on feedback.",
            temperature=0.4,
        )

        if isinstance(response, dict):
            nodes = response.get("nodes", sfd_data.get("nodes", []))
            edges = response.get("edges", sfd_data.get("edges", []))
        else:
            nodes = sfd_data.get("nodes", [])
            edges = sfd_data.get("edges", [])

        validation = self.validator.validate_sfd(nodes, edges)

        return {
            "nodes": nodes,
            "edges": edges,
            **validation,
        }

"""Causal Loop Diagram (CLD) builder service."""

import json

from app.services.llm.openrouter import OpenRouterLLM
from app.services.graph.validator import GraphValidator
from app.utils.sd_prompts import CLD_GENERATION_PROMPT


class CLDBuilder:
    """Builds and validates Causal Loop Diagrams from variables."""

    def __init__(self, llm: OpenRouterLLM | None = None) -> None:
        self.llm = llm or OpenRouterLLM()
        self.validator = GraphValidator()

    async def build_from_variables(self, variables: list[dict]) -> dict:
        """
        Build a CLD from a list of variables using the LLM.

        Args:
            variables: List of variable dicts with name, type, description.

        Returns:
            dict with keys: nodes, edges, valid, issues, feedback_loops
        """
        variables_json = json.dumps(variables, ensure_ascii=False, indent=2)
        prompt = CLD_GENERATION_PROMPT.format(variables=variables_json)

        response = await self.llm.chat_with_json_output(
            prompt=prompt,
            system="You are a system dynamics expert. Build causal loop diagrams with proper polarity. Return only valid JSON.",
            temperature=0.4,
        )

        # Normalize response format
        if isinstance(response, list):
            # LLM returned just edges
            nodes = [{"id": v["name"], "label": v["name"], "type": v.get("type", "variable")} for v in variables]
            edges = response
        elif isinstance(response, dict):
            nodes = response.get("nodes", [])
            edges = response.get("edges", [])
        else:
            nodes = []
            edges = []

        # Ensure all variables appear as nodes
        existing_ids = {n.get("id") for n in nodes}
        for var in variables:
            if var["name"] not in existing_ids:
                nodes.append({
                    "id": var["name"],
                    "label": var["name"],
                    "type": var.get("type", "variable"),
                })

        # Validate the CLD
        validation = self.validator.validate_cld(nodes, edges)

        return {
            "nodes": nodes,
            "edges": edges,
            **validation,
        }

    def build_from_equations(self, equations: list[dict]) -> dict:
        """
        Build a CLD from equations by parsing dependencies.

        Args:
            equations: List of equation dicts with lhs and rhs.

        Returns:
            dict with keys: nodes, edges, valid, issues, feedback_loops
        """
        import re

        nodes: list[dict] = []
        edges: list[dict] = []
        node_ids: set[str] = set()

        # Extract all variable names from LHS
        for eq in equations:
            lhs = eq.get("lhs", "")
            if lhs and lhs not in node_ids:
                var_type = eq.get("variable_type", "auxiliary")
                nodes.append({
                    "id": lhs,
                    "label": lhs,
                    "type": var_type,
                })
                node_ids.add(lhs)

        # Parse RHS to find dependencies and build edges
        for eq in equations:
            lhs = eq.get("lhs", "")
            rhs = eq.get("rhs", "")
            if not lhs or not rhs:
                continue

            # Find all variable references in RHS
            for node in nodes:
                ref_name = node["id"]
                if ref_name == lhs:
                    continue
                # Match as a whole word/identifier
                pattern = r'\b' + re.escape(ref_name) + r'\b'
                if re.search(pattern, rhs):
                    edges.append({
                        "source": ref_name,
                        "target": lhs,
                        "polarity": "+",
                    })
                    if ref_name not in node_ids:
                        nodes.append({
                            "id": ref_name,
                            "label": ref_name,
                            "type": "auxiliary",
                        })
                        node_ids.add(ref_name)

        # Validate
        validation = self.validator.validate_cld(nodes, edges)

        return {
            "nodes": nodes,
            "edges": edges,
            **validation,
        }

    async def enhance_cld(self, cld_data: dict, context: str) -> dict:
        """
        Enhance an existing CLD with additional context.

        Args:
            cld_data: Existing CLD with nodes and edges.
            context: Additional context to incorporate.

        Returns:
            Enhanced CLD data.
        """
        cld_json = json.dumps(cld_data, ensure_ascii=False, indent=2)
        prompt = (
            f"Enhance the following causal loop diagram with this additional context:\n\n"
            f"Context: {context}\n\n"
            f"Current CLD:\n{cld_json}\n\n"
            f"Return the enhanced CLD as JSON with 'nodes' and 'edges' arrays. "
            f"Add any missing variables or connections based on the context."
        )

        response = await self.llm.chat_with_json_output(
            prompt=prompt,
            system="You are a system dynamics expert. Enhance CLDs by adding relevant variables and causal links.",
            temperature=0.4,
        )

        if isinstance(response, dict):
            nodes = response.get("nodes", cld_data.get("nodes", []))
            edges = response.get("edges", cld_data.get("edges", []))
        else:
            nodes = cld_data.get("nodes", [])
            edges = cld_data.get("edges", [])

        validation = self.validator.validate_cld(nodes, edges)

        return {
            "nodes": nodes,
            "edges": edges,
            **validation,
        }

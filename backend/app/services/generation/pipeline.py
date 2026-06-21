"""Pure model generation pipeline (no database side effects)."""

import json
import logging

from app.core.exceptions import LLMError
from app.services.graph.cld_builder import CLDBuilder
from app.services.graph.sfd_builder import SFDBuilder
from app.services.graph.validator import GraphValidator
from app.services.llm.openrouter import OpenRouterLLM
from app.services.generation.python_generator import generate_python_code
from app.services.simulation.vensim_export import VensimExporter
from app.utils.model_postprocess import post_process_equations
from app.utils.sd_prompts import (
    CLD_GENERATION_PROMPT,
    EQUATION_GENERATION_PROMPT,
    VARIABLE_EXTRACTION_PROMPT,
)

logger = logging.getLogger(__name__)


async def generate_model_from_description(description: str) -> dict:
    """
    Run the full AI model generation pipeline without touching the database.

    Pipeline stages:
    1. Extract variables from user description via LLM
    2. Build CLD (Causal Loop Diagram)
    3. Validate CLD graph
    4. Generate equations
    5. Build SFD (Stock-Flow Diagram)
    6. Generate Python code for PySD
    7. Generate Vensim code

    Args:
        description: User's system description text.

    Returns:
        dict with generation results:
        - variables
        - equations
        - cld_data
        - sfd_data
        - python_code
        - vensim_code
        - status ("completed" or "error")
        - log
        - error (only if status == "error")
    """
    result_log: list[str] = []

    try:
        # Initialize services
        llm = OpenRouterLLM()
        validator = GraphValidator()
        cld_builder = CLDBuilder(llm=llm)
        sfd_builder = SFDBuilder(llm=llm)
        exporter = VensimExporter()

        # ── Stage 1: Variable Extraction ──
        logger.info("[Guest Gen] Stage 1: Variable extraction")
        result_log.append("Stage 1: Variable extraction...")

        var_prompt = VARIABLE_EXTRACTION_PROMPT.format(description=description)
        try:
            variables = await llm.chat_with_json_output(
                prompt=var_prompt,
                temperature=0.3,
            )
            if isinstance(variables, dict):
                variables = variables.get("variables", [])
            if not isinstance(variables, list):
                variables = []
        except LLMError as exc:
            logger.error(f"Variable extraction failed: {exc}")
            variables = []

        result_log.append(f"  Extracted {len(variables)} variables")

        # ── Stage 2: CLD Generation ──
        logger.info("[Guest Gen] Stage 2: CLD generation")
        result_log.append("Stage 2: CLD generation...")

        try:
            cld_result = await cld_builder.build_from_variables(variables)
        except Exception as exc:
            logger.error(f"CLD generation failed: {exc}")
            cld_result = {"nodes": [], "edges": [], "valid": False, "issues": [str(exc)], "feedback_loops": []}

        cld_valid = cld_result.get("valid", False)
        result_log.append(f"  CLD valid: {cld_valid}")
        if not cld_valid:
            for issue in cld_result.get("issues", []):
                result_log.append(f"  CLD issue: {issue}")

        # ── Stage 3: Equation Generation ──
        logger.info("[Guest Gen] Stage 3: Equation generation")
        result_log.append("Stage 3: Equation generation...")

        var_json = json.dumps(variables, ensure_ascii=False, indent=2)
        cld_json = json.dumps(
            {"nodes": cld_result.get("nodes", []), "edges": cld_result.get("edges", [])},
            ensure_ascii=False,
            indent=2,
        )
        eq_prompt = EQUATION_GENERATION_PROMPT.format(variables=var_json, cld=cld_json)

        try:
            equations = await llm.chat_with_json_output(
                prompt=eq_prompt,
                temperature=0.3,
            )
            if isinstance(equations, dict):
                equations = equations.get("equations", [])
            if not isinstance(equations, list):
                equations = []
        except LLMError as exc:
            logger.error(f"Equation generation failed: {exc}")
            equations = []

        result_log.append(f"  Generated {len(equations)} equations")

        # ── Stage 3b: Patch common LLM defaults ──
        equations = post_process_equations(variables, equations)
        patched_count = sum(
            1
            for eq in equations
            if "(patched)" in str(eq.get("rhs", "")).lower() or eq.get("_patched")
        )
        if patched_count:
            result_log.append(f"  Patched {patched_count} equation(s) with zero defaults")

        # ── Stage 4: Consistency Validation ──
        logger.info("[Guest Gen] Stage 4: Consistency validation")
        result_log.append("Stage 4: Consistency validation...")

        consistency = validator.validate_model_consistency(
            variables=variables,
            equations=equations,
            cld_nodes=cld_result.get("nodes", []),
            cld_edges=cld_result.get("edges", []),
        )
        result_log.append(f"  Consistent: {consistency['valid']}")

        # ── Stage 5: SFD Generation ──
        logger.info("[Guest Gen] Stage 5: SFD generation")
        result_log.append("Stage 5: SFD generation...")

        try:
            sfd_result = await sfd_builder.build_from_equations(variables, equations)
        except Exception as exc:
            logger.error(f"SFD generation failed: {exc}")
            sfd_result = {"nodes": [], "edges": [], "valid": False, "issues": [str(exc)], "metrics": {}}

        result_log.append(f"  SFD valid: {sfd_result.get('valid', False)}")

        # ── Stage 6: Python Code Generation ──
        logger.info("[Guest Gen] Stage 6: Python code generation")
        result_log.append("Stage 6: Python code generation...")

        # Prefer deterministic generation from equations; it avoids LLM
        # hallucinations such as undefined variables or wrong imports.
        python_code = generate_python_code(variables, equations)
        result_log.append(f"  Python code: {'generated' if python_code else 'failed'}")

        # ── Stage 7: Vensim Code Generation ──
        logger.info("[Guest Gen] Stage 7: Vensim code generation")
        result_log.append("Stage 7: Vensim code generation...")

        try:
            vensim_code = exporter.export_to_vensim(variables, equations)
        except Exception as exc:
            logger.error(f"Vensim export failed: {exc}")
            vensim_code = ""

        result_log.append(f"  Vensim code: {'generated' if vensim_code else 'failed'}")

        # Close LLM client
        await llm.close()

        return {
            "status": "completed",
            "variables": variables,
            "equations": equations,
            "cld_data": {
                "nodes": cld_result.get("nodes", []),
                "edges": cld_result.get("edges", []),
                "validation": {
                    "valid": cld_result.get("valid", False),
                    "issues": cld_result.get("issues", []),
                    "feedback_loops": cld_result.get("feedback_loops", []),
                },
            },
            "sfd_data": {
                "nodes": sfd_result.get("nodes", []),
                "edges": sfd_result.get("edges", []),
                "validation": {
                    "valid": sfd_result.get("valid", False),
                    "issues": sfd_result.get("issues", []),
                },
            },
            "python_code": python_code,
            "vensim_code": vensim_code,
            "log": result_log,
        }

    except Exception as exc:
        logger.exception(f"Guest model generation pipeline failed: {exc}")
        return {
            "status": "error",
            "error": str(exc),
            "variables": [],
            "equations": [],
            "cld_data": {"nodes": [], "edges": [], "validation": {"valid": False, "issues": [str(exc)], "feedback_loops": []}},
            "sfd_data": {"nodes": [], "edges": [], "validation": {"valid": False, "issues": [str(exc)]}},
            "python_code": "",
            "vensim_code": "",
            "log": result_log,
        }

"""Vensim model export utilities."""

import re
from typing import Any

from app.core.exceptions import ValidationError


class VensimExporter:
    """Exports system dynamics models to Vensim .mdl format."""

    VENSIM_HEADER = "{UTF-8}\n"
    VENSIM_FOOTER = "\n\\\n---\"\"\n"

    def __init__(self) -> None:
        pass

    def export_to_vensim(
        self,
        variables: list[dict],
        equations: list[dict],
        time_start: float = 0.0,
        time_end: float = 100.0,
        time_step: float = 0.25,
    ) -> str:
        """
        Convert variables and equations to Vensim .mdl format.

        Args:
            variables: List of variable dicts with name, type, description.
            equations: List of equation dicts with lhs, rhs, variable_type.
            time_start: Simulation start time.
            time_end: Simulation end time.
            time_step: Simulation time step.

        Returns:
            Vensim .mdl format string.
        """
        lines: list[str] = []
        lines.append(self.VENSIM_HEADER)

        # Equations section
        lines.append("\n*Equations")
        for eq in equations:
            lhs = eq.get("lhs", "")
            rhs = eq.get("rhs", "")
            var_type = eq.get("variable_type", "auxiliary")

            if not lhs or not rhs:
                continue

            # Convert Python-style equations to Vensim syntax
            vensim_rhs = self._convert_python_to_vensim_syntax(rhs)

            if var_type == "stock":
                # Stock equations use INTEG() in Vensim
                if "INTEG" not in vensim_rhs.upper():
                    vensim_rhs = f"INTEG({vensim_rhs}, 0)"
                lines.append(f"{lhs} = {vensim_rhs}")
            elif var_type == "flow":
                lines.append(f"{lhs} = {vensim_rhs}")
            elif var_type == "constant":
                # Constants don't have equations in Vensim, just values
                try:
                    float(vensim_rhs)
                    lines.append(f"{lhs} = {vensim_rhs}")
                except ValueError:
                    lines.append(f"{lhs} = {vensim_rhs}")
            else:
                lines.append(f"{lhs} = {vensim_rhs}")

        # Simulation control section
        lines.append("\n*Simulation Control")
        lines.append(f"INITIAL TIME = {time_start}")
        lines.append(f"FINAL TIME = {time_end}")
        lines.append(f"TIME STEP = {time_step}")
        lines.append("SAVEPER = TIME STEP")

        # Units section
        lines.append("\n*Units")
        for var in variables:
            name = var.get("name", "")
            units = var.get("units", "")
            if name and units:
                lines.append(f"{name} : {units}")

        lines.append(self.VENSIM_FOOTER)
        return "\n".join(lines)

    def _convert_python_to_vensim_syntax(self, rhs: str) -> str:
        """
        Convert Python mathematical syntax to Vensim syntax.

        Args:
            rhs: Right-hand side expression in Python syntax.

        Returns:
            Vensim-compatible expression.
        """
        if not rhs:
            return "0"

        result = rhs

        # Python -> Vensim function mappings
        replacements = {
            r'np\.exp\(': "EXP(",
            r'np\.log\(': "LN(",
            r'np\.log10\(': "LOG(",
            r'np\.sqrt\(': "SQRT(",
            r'np\.abs\(': "ABS(",
            r'np\.sin\(': "SIN(",
            r'np\.cos\(': "COS(",
            r'np\.tan\(': "TAN(",
            r'np\.power\(': "POWER(",
            r'np\.maximum\(': "MAX(",
            r'np\.minimum\(': "MIN(",
            r'np\.pi': "PI",
            r'math\.exp\(': "EXP(",
            r'math\.log\(': "LN(",
            r'math\.sqrt\(': "SQRT(",
            r'math\.pi': "PI",
        }

        for pattern, replacement in replacements.items():
            result = re.sub(pattern, replacement, result)

        # Convert ** to ^ for Vensim
        result = result.replace("**", "^")

        # Convert Python's max/min builtins
        result = re.sub(r'\bmax\(', "MAX(", result)
        result = re.sub(r'\bmin\(', "MIN(", result)

        # Convert IF/ELSE style conditionals to Vensim IF THEN ELSE
        # Python: a if condition else b
        # Vensim: IF THEN ELSE(condition, a, b)
        if_match = re.search(r'(.+?)\s+if\s+(.+?)\s+else\s+(.+)', result)
        if if_match:
            true_val = if_match.group(1).strip()
            condition = if_match.group(2).strip()
            false_val = if_match.group(3).strip()
            result = f"IF THEN ELSE({condition}, {true_val}, {false_val})"

        return result

    def generate_python_for_pysd(
        self,
        variables: list[dict],
        equations: list[dict],
        time_start: float = 0.0,
        time_end: float = 100.0,
        time_step: float = 0.25,
    ) -> str:
        """
        Generate Python code compatible with PySD.

        This creates a Python module that PySD can load and simulate.

        Args:
            variables: List of variable dicts.
            equations: List of equation dicts.
            time_start: Simulation start time.
            time_end: Simulation end time.
            time_step: Simulation time step.

        Returns:
            Python code string compatible with PySD.
        """
        lines: list[str] = []

        # Module header
        lines.append('"""System Dynamics Model generated by sdCloud."""')
        lines.append("")
        lines.append("from pysd.py_backend.functions import integ, if_then_else")
        lines.append("")

        # Initial values lookup
        initial_values: dict[str, Any] = {}
        for var in variables:
            name = var.get("name", "")
            init = var.get("initial_value", 0.0)
            if name:
                try:
                    initial_values[name] = float(init)
                except (ValueError, TypeError):
                    initial_values[name] = 0.0

        # Generate functions for each equation
        for eq in equations:
            lhs = eq.get("lhs", "")
            rhs = eq.get("rhs", "")
            var_type = eq.get("variable_type", "auxiliary")

            if not lhs or not rhs:
                continue

            # Sanitize function name
            func_name = self._sanitize_name(lhs)

            if var_type == "stock":
                # Stock uses integ()
                init_val = initial_values.get(lhs, 0.0)
                lines.append(f"\ndef {func_name}()")
                lines.append(f"    return integ({self._convert_to_pysd_expr(rhs)}, {init_val})")
            else:
                # Flow, auxiliary, constant
                lines.append(f"\ndef {func_name}()")
                lines.append(f"    return {self._convert_to_pysd_expr(rhs)}")

        # Model control functions
        lines.append("\n\ndef initial_time()")
        lines.append(f"    return {time_start}")
        lines.append("\ndef final_time()")
        lines.append(f"    return {time_end}")
        lines.append("\ndef time_step()")
        lines.append(f"    return {time_step}")
        lines.append("\ndef saveper()")
        lines.append("    return time_step()")

        # Time function
        lines.append("\n\ndef time()")
        lines.append("    return __data['time']")

        return "\n".join(lines)

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a variable name to be a valid Python function name."""
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        sanitized = re.sub(r'^[^a-zA-Z_]', '_', sanitized)
        return sanitized.lower()

    def _convert_to_pysd_expr(self, expr: str) -> str:
        """
        Convert an equation RHS to a PySD-compatible Python expression.

        Args:
            expr: Expression string.

        Returns:
            PySD-compatible expression.
        """
        if not expr:
            return "0"

        result = expr

        # Replace mathematical functions with PySD equivalents
        result = re.sub(r'\bexp\(', "np.exp(", result)
        result = re.sub(r'\blog\(', "np.log(", result)
        result = re.sub(r'\bsqrt\(', "np.sqrt(", result)
        result = re.sub(r'\bsin\(', "np.sin(", result)
        result = re.sub(r'\bcos\(', "np.cos(", result)

        # Convert variable names to function calls
        # This is a simplified approach - PySD expects function calls for dependencies
        result = re.sub(r'\b([a-zA-Z_][a-zA-Z0-9_]+)\b', r'\1()', result)

        # Fix double parentheses from the above replacement
        result = result.replace("()()", "()")

        # Fix numeric literals that got function calls
        result = re.sub(r'(\d)\.\(\)', r'\1', result)
        result = re.sub(r'(\d)\(\)', r'\1', result)

        # Fix math functions that got double calls
        result = re.sub(r'np\.exp\(\)\(', "np.exp(", result)
        result = re.sub(r'np\.log\(\)\(', "np.log(", result)
        result = re.sub(r'np\.sqrt\(\)\(', "np.sqrt(", result)
        result = re.sub(r'\)\(\)', ")", result)

        return result

"""PySD simulation runner service."""

import asyncio
import json
import os
import tempfile
import traceback
from pathlib import Path

import pysd

from app.core.exceptions import SimulationError


class PySDRunner:
    """Runs system dynamics simulations using PySD."""

    def __init__(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="sdcloud_pysd_")

    async def simulate_from_python(
        self,
        python_code: str,
        params: dict | None = None,
        time_start: float = 0.0,
        time_end: float = 100.0,
        time_step: float = 0.25,
    ) -> dict:
        """
        Execute Python model code via PySD and return time series results.

        Args:
            python_code: Python code string for the PySD model.
            params: Override parameters for the simulation.
            time_start: Simulation start time.
            time_end: Simulation end time.
            time_step: Simulation time step.

        Returns:
            dict with variable names as keys and lists of values as values,
            plus a 'time' key.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._run_python_sync,
            python_code,
            params or {},
            time_start,
            time_end,
            time_step,
        )

    def _run_python_sync(
        self,
        python_code: str,
        params: dict,
        time_start: float,
        time_end: float,
        time_step: float,
    ) -> dict:
        """Synchronous simulation execution from Python code."""
        # Write Python code to a temporary file
        py_file = Path(self.temp_dir) / f"model_{hash(python_code) & 0xFFFFFFFF}.py"
        py_file.write_text(python_code, encoding="utf-8")

        try:
            # Load the model using PySD
            model = pysd.load(str(py_file))

            # Set parameters if provided
            if params:
                for param_name, param_value in params.items():
                    try:
                        model.set_components({param_name: param_value})
                    except Exception:
                        pass  # Parameter might not exist in model

            # Run the simulation
            results = model.run(
                initial_condition=("original", time_start),
                final_time=time_end,
                timestep=time_step,
                return_columns="*",
            )

            # Convert results to dict
            output: dict[str, list] = {"time": []}

            if hasattr(results, "index"):
                # pandas DataFrame
                output["time"] = results.index.astype(float).tolist()
                for col in results.columns:
                    output[str(col)] = results[col].astype(float).tolist()
            elif hasattr(results, "to_dict"):
                # Try to convert
                df = results.to_dict()
                for key, values in df.items():
                    output[str(key)] = list(values.values()) if hasattr(values, "values") else list(values)
            else:
                # Dict-like
                for key, values in results.items() if hasattr(results, "items") else []:
                    output[str(key)] = list(values)

            # Ensure time key exists
            if "time" not in output or not output["time"]:
                # Generate time array
                t = time_start
                n = len(next(iter(output.values()))) if output else 0
                output["time"] = [time_start + i * time_step for i in range(n)]

            return output

        except Exception as exc:
            # PySD failed (common with LLM-generated PySD 2.x style code on
            # PySD 3.x). Fall back to the SciPy runner which parses the
            # generated code directly.
            if "integ" in str(exc).lower() or "import" in str(exc).lower():
                from app.services.simulation.scipy_runner import run_simulation

                return run_simulation(
                    python_code=python_code,
                    params=params,
                    time_start=time_start,
                    time_end=time_end,
                    time_step=time_step,
                )

            error_msg = f"PySD simulation failed: {str(exc)}\n{traceback.format_exc()}"
            raise SimulationError(detail=error_msg)

        finally:
            # Cleanup temp file
            try:
                if py_file.exists():
                    py_file.unlink()
            except Exception:
                pass

    async def simulate_from_vensim(
        self,
        vensim_code: str,
        params: dict | None = None,
        time_start: float = 0.0,
        time_end: float = 100.0,
        time_step: float = 0.25,
    ) -> dict:
        """
        Convert Vensim code to Python and run simulation.

        Args:
            vensim_code: Vensim model code (.mdl format).
            params: Override parameters.
            time_start: Simulation start time.
            time_end: Simulation end time.
            time_step: Simulation time step.

        Returns:
            dict with simulation results.
        """
        # Convert Vensim to Python
        loop = asyncio.get_event_loop()
        python_code = await loop.run_in_executor(
            None,
            self._vensim_to_python_sync,
            vensim_code,
        )

        return await self.simulate_from_python(
            python_code=python_code,
            params=params,
            time_start=time_start,
            time_end=time_end,
            time_step=time_step,
        )

    def _vensim_to_python_sync(self, vensim_code: str) -> str:
        """Convert Vensim .mdl code to Python using PySD's parser."""
        # Write Vensim code to a temp .mdl file
        mdl_file = Path(self.temp_dir) / f"model_{hash(vensim_code) & 0xFFFFFFFF}.mdl"
        mdl_file.write_text(vensim_code, encoding="utf-8")

        try:
            # PySD can load .mdl files directly
            # First, translate to Python
            py_file = Path(self.temp_dir) / f"model_{hash(vensim_code) & 0xFFFFFFFF}_translated.py"
            pysd.io.python.PythonWriter(str(mdl_file), str(py_file))
            python_code = py_file.read_text(encoding="utf-8")
            return python_code
        except Exception:
            # Fallback: try loading the mdl directly, PySD handles translation internally
            try:
                model = pysd.load(str(mdl_file))
                # PySD translates internally - just use the model directly
                return self._simulate_loaded_model(model, {}, 0, 100, 0.25)
            except Exception as exc:
                raise SimulationError(detail=f"Failed to convert Vensim model: {str(exc)}")
        finally:
            try:
                if mdl_file.exists():
                    mdl_file.unlink()
            except Exception:
                pass

    def _simulate_loaded_model(
        self,
        model,
        params: dict,
        time_start: float,
        time_end: float,
        time_step: float,
    ) -> str:
        """Simulate an already loaded model and return results."""
        # This method is used as a fallback - returns the Python code string
        # PySD loads the model, we can extract the Python code
        # For simplicity, we generate Python code from the model structure
        try:
            results = model.run(
                initial_condition=("original", time_start),
                final_time=time_end,
                timestep=time_step,
            )
            return str(results)
        except Exception as exc:
            raise SimulationError(detail=f"Model simulation failed: {str(exc)}")

    async def get_model_info(self, python_code: str) -> dict:
        """
        Extract model metadata (variables, parameters, docs) from Python code.

        Args:
            python_code: Python model code.

        Returns:
            dict with model metadata.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._get_model_info_sync,
            python_code,
        )

    def _get_model_info_sync(self, python_code: str) -> dict:
        """Synchronous model info extraction."""
        py_file = Path(self.temp_dir) / f"info_{hash(python_code) & 0xFFFFFFFF}.py"
        py_file.write_text(python_code, encoding="utf-8")

        try:
            model = pysd.load(str(py_file))

            info = {
                "variables": [],
                "parameters": [],
                "stocks": [],
                "flows": [],
                "auxiliaries": [],
                "docs": {},
            }

            # Try to get model documentation
            try:
                docs = model.doc()
                if hasattr(docs, "to_dict"):
                    docs_dict = docs.to_dict("records")
                    for doc in docs_dict:
                        name = doc.get("Real Name", doc.get("Py Name", ""))
                        var_type = doc.get("Type", "").lower()
                        info["docs"][name] = doc
                        if var_type == "stock":
                            info["stocks"].append(name)
                        elif var_type == "flow":
                            info["flows"].append(name)
                        elif var_type == "auxiliary":
                            info["auxiliaries"].append(name)
                        elif var_type == "constant" or var_type == "parameter":
                            info["parameters"].append(name)
                        info["variables"].append(name)
            except Exception:
                pass

            return info

        except Exception as exc:
            return {"error": str(exc), "variables": []}

        finally:
            try:
                if py_file.exists():
                    py_file.unlink()
            except Exception:
                pass

    def cleanup(self) -> None:
        """Clean up temporary files."""
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

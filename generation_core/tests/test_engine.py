import math

import pytest
from pydantic import ValidationError

from pipeline.codegen import export_vensim, generate_python_code
from pipeline.exceptions import ModelValidationError, SimulationError
from pipeline.formats import export_xmile
from pipeline.generation import generate_model
from pipeline.ir import call, lit
from pipeline.schemas import ModelDocument, SimulationParameters
from pipeline.simulation import engine, simulate_model


async def test_generation_and_simulation(generation_request, fixture_llm, tmp_path):
    document = await generate_model(generation_request, fixture_llm, workdir=tmp_path)
    assert document.schema_version == "2.0"
    assert len(document.variables) == 10
    assert document.validation.status == "passed"
    assert document.sfd_data.validation.valid
    assert "def prey():" in generate_python_code(document)
    assert "INTEG(" in export_vensim(document)
    assert "prey_births" in export_vensim(document)
    assert "<xmile" in export_xmile(document)
    assert (tmp_path / "stage.json").is_file()

    result = simulate_model(document, SimulationParameters(final_time=1, time_step=0.25))
    assert result.engine == "pysd"
    assert result.fallback_reason is None
    assert len(result.time) == 5
    assert len(result.variables) == 10
    assert result.variables["prey"][0] == 100
    assert result.variables["predators"][0] == 20
    assert all(math.isfinite(value) for values in result.variables.values() for value in values)

    import pysd

    vensim_path = tmp_path / "model.mdl"
    vensim_path.write_text(export_vensim(document), encoding="utf-8")
    model = pysd.read_vensim(str(vensim_path))
    frame = model.run(final_time=1, time_step=0.25, saveper=0.25)
    assert len(frame.index) == 5
    assert frame["prey"].iloc[0] == pytest.approx(100)


async def test_scipy_fallback(generation_request, fixture_llm, monkeypatch):
    document = await generate_model(generation_request, fixture_llm)

    def fail_pysd(*args):
        raise RuntimeError("forced PySD failure")

    monkeypatch.setattr(engine, "_run_pysd", fail_pysd)
    result = simulate_model(document, SimulationParameters(final_time=1, time_step=0.25))
    assert result.engine == "scipy"
    assert result.integration_method == "euler"
    assert "forced PySD failure" in result.fallback_reason
    assert set(result.variables) == {item.id for item in document.variables}


async def test_arbitrary_python_field_is_rejected(generation_request, fixture_llm):
    document = await generate_model(generation_request, fixture_llm)
    payload = document.model_dump(mode="json")
    payload["python_code"] = "raise RuntimeError('untrusted code')"
    with pytest.raises(ValidationError):
        ModelDocument.model_validate(payload)


async def test_malicious_equation_is_rejected(generation_request, fixture_llm):
    document = await generate_model(generation_request, fixture_llm)
    variables = [item.model_dump() for item in document.variables]
    for item in variables:
        if item["id"] == "prey_births":
            item["expression"] = call("__import__", lit(1)).model_dump(mode="json")
    document = ModelDocument.model_validate(document.model_dump() | {"variables": variables})
    with pytest.raises(ModelValidationError, match="UNKNOWN_FUNCTION"):
        simulate_model(document, SimulationParameters())


def test_simulation_grid_limit():
    with pytest.raises(SimulationError, match="at most 10000"):
        from tests.helpers import exponential_model

        simulate_model(
            exponential_model(),
            SimulationParameters(final_time=10000, time_step=0.1, saveper=0.1),
        )

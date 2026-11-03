import pytest

from pipeline.exceptions import SimulationError
from pipeline.graphs import validate_sfd
from pipeline.postprocess import post_process_equations
from pipeline.schemas import SFDEdge, SFDNode, SimulationParameters
from pipeline.simulation import engine, simulate_model
from tests.helpers import exponential_model


def test_zero_stock_is_not_replaced():
    equations = post_process_equations(
        [{"name": "recovered", "type": "stock", "initial_value": 0}],
        [{"lhs": "recovered", "rhs": "integ(recovering, 0)", "variable_type": "stock"}],
    )
    assert equations[0]["rhs"] == "integ(recovering, 0)"


def test_requested_method_matches_numerics():
    model = exponential_model()
    euler = simulate_model(
        model,
        SimulationParameters(final_time=1, time_step=0.25, integration_method="euler"),
    )
    rk45 = simulate_model(
        model,
        SimulationParameters(final_time=1, time_step=0.25, integration_method="rk45"),
    )
    assert euler.variables["population"][-1] == pytest.approx(110.3812890625)
    assert rk45.variables["population"][-1] == pytest.approx(110.5170918, rel=1e-6)
    assert rk45.integration_method == "rk45"


def test_fallback_returns_all_series_and_validates_grid(monkeypatch):
    document = exponential_model()
    monkeypatch.setattr(
        engine, "_run_pysd", lambda *args: (_ for _ in ()).throw(RuntimeError("forced"))
    )
    result = simulate_model(document, SimulationParameters(final_time=1, time_step=0.25))
    assert set(result.variables) == {"population", "growth", "growth_rate"}
    with pytest.raises(SimulationError, match="time_step"):
        simulate_model(document, SimulationParameters(final_time=1, time_step=0.3))


def test_dangling_flow_is_invalid():
    validation = validate_sfd(
        [SFDNode(id="x", label="x", type="stock"), SFDNode(id="f", label="f", type="flow")],
        [SFDEdge(source="f", target="x", type="flow")],
    )
    assert not validation.valid

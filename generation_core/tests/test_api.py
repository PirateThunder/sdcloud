from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from service.config import Settings, get_settings
from service.database import get_db
from service.jobs.dependencies import get_dispatcher
from service.jobs.tasks import execute_job
from service.main import app
from service.models import Base

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "llm_responses.json"


@pytest.fixture
async def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fixture")
    monkeypatch.setenv("LLM_FIXTURE_PATH", str(FIXTURE))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jobs_root=tmp_path / "jobs",
        api_key="test-key",
        job_timeout=60,
    )
    dispatches = []

    async def override_db():
        async with factory() as session:
            yield session

    async def fake_dispatch(job_id: str) -> None:
        dispatches.append(job_id)
        async with factory() as session:
            await execute_job(job_id, session=session, settings=settings)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_dispatcher] = lambda: fake_dispatch
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.dispatches = dispatches
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


def auth(key: str = "generation-key") -> dict[str, str]:
    return {"X-API-Key": "test-key", "Idempotency-Key": key}


async def test_health_and_api_key(api_client):
    assert (await api_client.get("/health")).status_code == 200
    assert (await api_client.get("/api/v1/jobs")).status_code == 401


async def test_rest_generation_simulation_and_idempotency(api_client):
    request = {
        "description": "Модель хищник-жертва: кролики размножаются, лисы едят кроликов.",
        "history": [],
    }
    created = await api_client.post("/api/v1/models", json=request, headers=auth())
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]

    replay = await api_client.post("/api/v1/models", json=request, headers=auth())
    assert replay.status_code == 200
    assert replay.json()["job_id"] == job_id
    assert len(api_client.dispatches) == 1

    conflict = await api_client.post(
        "/api/v1/models",
        json={**request, "description": "Другая модель"},
        headers=auth(),
    )
    assert conflict.status_code == 409

    status = await api_client.get(f"/api/v1/jobs/{job_id}", headers=auth())
    assert status.status_code == 200
    assert status.json()["status"] == "done", status.text
    assert status.json()["stage"] == "done"

    result = await api_client.get(f"/api/v1/jobs/{job_id}/result", headers=auth())
    assert result.status_code == 200
    document = result.json()
    assert document["schema_version"] == "2.0"
    assert len(document["variables"]) == 10

    code = await api_client.get(f"/api/v1/jobs/{job_id}/files/model.py", headers=auth())
    assert code.status_code == 200
    assert "def prey():" in code.text
    xmile = await api_client.get(f"/api/v1/jobs/{job_id}/files/model.xmile", headers=auth())
    assert xmile.status_code == 200

    simulation = await api_client.post(
        "/api/v1/simulations",
        json={
            "model": document,
            "parameters": {"time_start": 0, "time_end": 1, "time_step": 0.25},
        },
        headers=auth("simulation-key"),
    )
    assert simulation.status_code == 202, simulation.text
    simulation_id = simulation.json()["job_id"]
    simulation_result = await api_client.get(f"/api/v1/jobs/{simulation_id}/result", headers=auth())
    assert simulation_result.status_code == 200, simulation_result.text
    payload = simulation_result.json()
    assert payload["schema_version"] == "2.0"
    assert payload["engine"] == "pysd"
    assert payload["integration_method"] == "euler"
    assert len(payload["time"]) == 5
    assert len(payload["variables"]) == 10
    csv = await api_client.get(f"/api/v1/jobs/{simulation_id}/files/simulation.csv", headers=auth())
    assert csv.status_code == 200
    assert csv.text.splitlines()[0].startswith("time,")


async def test_rest_chat_generates_then_answers_without_a_new_model(api_client):
    created = await api_client.post(
        "/api/v1/chat",
        json={"description": "Predator prey model with rabbits and foxes", "history": []},
        headers=auth("chat-model"),
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    response = (await api_client.get(f"/api/v1/jobs/{job_id}/result", headers=auth())).json()
    assert response["kind"] == "model"
    assert response["model"]["schema_version"] == "2.0"
    assert (
        await api_client.get(f"/api/v1/jobs/{job_id}/files/model.py", headers=auth())
    ).status_code == 200

    question = await api_client.post(
        "/api/v1/chat",
        json={
            "description": "What is the prey growth rate?",
            "history": [{"role": "assistant", "content": response["assistant_text"]}],
            "base_model": response["model"],
        },
        headers=auth("chat-question"),
    )
    assert question.status_code == 202, question.text
    answer = (
        await api_client.get(f"/api/v1/jobs/{question.json()['job_id']}/result", headers=auth())
    ).json()
    assert answer["kind"] == "answer"
    assert answer["model"] is None
    assert "0.1 per year" in answer["assistant_text"]


async def test_rest_vensim_import(api_client):
    source = (ROOT / "tests" / "fixtures" / "models" / "teacup.mdl").read_bytes()
    response = await api_client.post(
        "/api/v1/models/import",
        files={"file": ("teacup.mdl", source, "text/plain")},
        headers=auth("import-key"),
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    status = await api_client.get(f"/api/v1/jobs/{job_id}", headers=auth())
    assert status.json()["status"] == "done", status.text
    result = await api_client.get(f"/api/v1/jobs/{job_id}/result", headers=auth())
    assert result.json()["provenance"]["kind"] == "vensim_import"
    assert any(item["id"] == "teacup_temperature" for item in result.json()["variables"])
    assert (
        await api_client.get(f"/api/v1/jobs/{job_id}/files/model.xmile", headers=auth())
    ).status_code == 200

    replay = await api_client.post(
        "/api/v1/models/import",
        files={"file": ("teacup.mdl", source, "text/plain")},
        headers=auth("import-key"),
    )
    assert replay.status_code == 200
    assert replay.json()["job_id"] == job_id


async def test_result_is_not_ready_for_unknown_job(api_client):
    response = await api_client.get("/api/v1/jobs/not-found/result", headers=auth())
    assert response.status_code == 404


async def test_retry_failed_job(api_client, monkeypatch):
    monkeypatch.setenv("LLM_FIXTURE_PATH", str(FIXTURE.parent / "missing.json"))
    request = {"description": "Модель хищник-жертва", "history": []}
    created = await api_client.post("/api/v1/models", json=request, headers=auth("retry-key"))
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    failed = await api_client.get(f"/api/v1/jobs/{job_id}", headers=auth())
    assert failed.json()["status"] == "error"

    monkeypatch.setenv("LLM_FIXTURE_PATH", str(FIXTURE))
    retried = await api_client.post(f"/api/v1/jobs/{job_id}/retry", headers=auth())
    assert retried.status_code == 200, retried.text
    completed = await api_client.get(f"/api/v1/jobs/{job_id}", headers=auth())
    assert completed.json()["status"] == "done", completed.text
    assert completed.json()["attempt"] == 2


async def test_analysis_endpoints(api_client):
    created = await api_client.post(
        "/api/v1/models",
        json={"description": "Модель хищник-жертва", "history": []},
        headers=auth("analysis-model"),
    )
    model_job = created.json()["job_id"]
    model = (await api_client.get(f"/api/v1/jobs/{model_job}/result", headers=auth())).json()
    simulation = await api_client.post(
        "/api/v1/simulations",
        json={"model": model, "parameters": {"final_time": 1, "time_step": 0.25}},
        headers=auth("analysis-baseline"),
    )
    baseline_job = simulation.json()["job_id"]
    baseline = (await api_client.get(f"/api/v1/jobs/{baseline_job}/result", headers=auth())).json()

    scenarios = await api_client.post(
        "/api/v1/scenario-runs",
        json={
            "model": model,
            "parameters": {"final_time": 1, "time_step": 0.25},
            "scenarios": [{"name": "base"}, {"name": "high", "parameters": {"prey_growth": 0.2}}],
        },
        headers=auth("scenario-run"),
    )
    assert scenarios.status_code == 202, scenarios.text
    scenario_id = scenarios.json()["job_id"]
    scenario_result = (
        await api_client.get(f"/api/v1/jobs/{scenario_id}/result", headers=auth())
    ).json()
    assert scenario_result["status"] == "done"
    assert (
        await api_client.get(f"/api/v1/jobs/{scenario_id}/files/comparison.csv", headers=auth())
    ).status_code == 200

    sensitivity = await api_client.post(
        "/api/v1/sensitivity-runs",
        json={
            "model": model,
            "parameters": {"final_time": 1, "time_step": 0.25},
            "runs": 3,
            "seed": 42,
            "targets": [
                {"name": "prey_growth", "distribution": "uniform", "low": 0.05, "high": 0.2}
            ],
        },
        headers=auth("sensitivity-run"),
    )
    assert sensitivity.status_code == 202, sensitivity.text
    sensitivity_id = sensitivity.json()["job_id"]
    sensitivity_result = (
        await api_client.get(f"/api/v1/jobs/{sensitivity_id}/result", headers=auth())
    ).json()
    assert sensitivity_result["successful_runs"] == 3
    assert (
        await api_client.get(f"/api/v1/jobs/{sensitivity_id}/files/sensitivity.csv", headers=auth())
    ).status_code == 200

    times = [0, 0.5, 1]
    observations = [baseline["variables"]["prey"][baseline["time"].index(value)] for value in times]
    calibration = await api_client.post(
        "/api/v1/calibrations",
        json={
            "model": model,
            "parameters": {"final_time": 1, "time_step": 0.25},
            "targets": [{"name": "prey_growth", "initial": 0.2, "low": 0.01, "high": 0.5}],
            "time": times,
            "observations": {"prey": observations},
        },
        headers=auth("calibration-run"),
    )
    assert calibration.status_code == 202, calibration.text
    calibration_id = calibration.json()["job_id"]
    calibration_result = (
        await api_client.get(f"/api/v1/jobs/{calibration_id}/result", headers=auth())
    ).json()
    assert calibration_result["success"] is True
    assert calibration_result["fitted_parameters"]["prey_growth"] == pytest.approx(0.1, abs=1e-5)
    assert calibration_result["fitted_model"]["provenance"]["kind"] == "calibration"
    assert (
        await api_client.get(
            f"/api/v1/jobs/{calibration_id}/files/fitted_model.json", headers=auth()
        )
    ).status_code == 200

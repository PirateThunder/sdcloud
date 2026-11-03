import uuid
from datetime import timedelta

from sqlalchemy import select

from app.database import SessionFactory, utc_now
from app.generations.models import Generation
from app.generations.tasks import execute_generation
from app.models.models import Model, ModelVersion
from app.simulations.models import Simulation
from app.simulations.tasks import execute_simulation
from tests.helpers import FakeCore, create_conversation, login


async def submit_generation(client, headers, conversation_id, key="generation-key-1") -> str:
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Population model"},
        headers={**headers, "Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()["generation_id"]


async def test_generation_simulation_versions_and_snapshot_export(client):
    headers = await login(client, "workflow@example.com")
    conversation_id = await create_conversation(client, headers)
    generation_id = await submit_generation(client, headers, conversation_id)
    core = FakeCore()

    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(generation_id), db=db, client=core)

    generation = await client.get(f"/api/v1/generations/{generation_id}", headers=headers)
    assert generation.json()["status"] == "done", generation.text
    version_id = generation.json()["model_version_id"]
    detail = await client.get(f"/api/v1/model-versions/{version_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["document"]["schema_version"] == "2.0"
    assert set(detail.json()["available_exports"]) == {"python", "vensim", "xmile"}

    exported = await client.get(
        f"/api/v1/models/{detail.json()['model_id']}/versions/1/export?format=python",
        headers=headers,
    )
    assert exported.status_code == 200
    assert exported.text == "generated model.py"

    simulation = await client.post(
        f"/api/v1/model-versions/{version_id}/simulations",
        json={"parameters": {"final_time": 1, "time_step": 0.25}},
        headers={**headers, "Idempotency-Key": "simulation-key-1"},
    )
    assert simulation.status_code == 202, simulation.text
    simulation_id = simulation.json()["id"]
    async with SessionFactory() as db:
        await execute_simulation(uuid.UUID(simulation_id), db=db, client=core)
    finished = await client.get(f"/api/v1/simulations/{simulation_id}", headers=headers)
    assert finished.json()["status"] == "done", finished.text
    assert finished.json()["engine"] == "pysd"
    assert len(finished.json()["result"]["variables"]["population"]) == 5

    second_generation = await submit_generation(
        client, headers, conversation_id, "generation-key-2"
    )
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(second_generation), db=db, client=core)
        versions = list((await db.scalars(select(ModelVersion))).all())
        assert len(versions) == 2
        assert {version.version for version in versions} == {1, 2}
        assert len({version.model_id for version in versions}) == 1
        assert (
            await db.scalar(select(Model).where(Model.owner_id == uuid.UUID(headers["user_id"])))
            is not None
        )

    other = await login(client, "intruder@example.com")
    assert (
        await client.get(f"/api/v1/model-versions/{version_id}", headers=other)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/simulations/{simulation_id}", headers=other)
    ).status_code == 404


async def test_chat_answers_questions_and_updates_use_current_model(client):
    headers = await login(client, "dialog@example.com")
    conversation_id = await create_conversation(client, headers)
    first_id = await submit_generation(client, headers, conversation_id)
    first_core = FakeCore()
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(first_id), db=db, client=first_core)
    assert first_core.chat_payloads[0]["base_model"] is None

    question = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "What is the growth rate?"},
        headers={**headers, "Idempotency-Key": "question-key-1"},
    )
    question_id = question.json()["generation_id"]
    answer_core = FakeCore(
        response={
            "kind": "answer",
            "assistant_text": "The growth rate is **0.1 per year**.",
            "model": None,
        }
    )
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(question_id), db=db, client=answer_core)
        assert len(list((await db.scalars(select(ModelVersion))).all())) == 1
    assert answer_core.chat_payloads[0]["base_model"]["id"] == "population_model"
    answered = await client.get(f"/api/v1/generations/{question_id}", headers=headers)
    assert answered.json()["status"] == "done"
    assert answered.json()["model_version_id"] is None

    update_id = await submit_generation(client, headers, conversation_id, "update-key-1")
    update_core = FakeCore()
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(update_id), db=db, client=update_core)
        assert len(list((await db.scalars(select(ModelVersion))).all())) == 2
    update_payload = update_core.chat_payloads[0]
    assert update_payload["base_model"]["id"] == "population_model"
    assert {item["role"] for item in update_payload["history"]} == {"user", "assistant"}
    assert any("0.1 per year" in item["content"] for item in update_payload["history"])


async def test_generation_malformed_result_and_retry(client):
    headers = await login(client, "malformed@example.com")
    conversation_id = await create_conversation(client, headers)
    generation_id = await submit_generation(client, headers, conversation_id)
    malformed = FakeCore(document={"schema_version": "2.0", "name": "broken"})
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(generation_id), db=db, client=malformed)
        generation = await db.get(Generation, uuid.UUID(generation_id))
        assert generation.status == "error"
        assert generation.error == "generator returned an invalid model document"
        assert await db.scalar(select(ModelVersion)) is None

    retry = await client.post(f"/api/v1/generations/{generation_id}/retry", headers=headers)
    assert retry.status_code == 202
    assert retry.json()["id"] != generation_id
    assert retry.json()["attempt"] == 2
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(retry.json()["id"]), db=db, client=FakeCore())
    finished = await client.get(f"/api/v1/generations/{retry.json()['id']}", headers=headers)
    assert finished.json()["status"] == "done"


async def test_core_error_is_sanitized(client):
    headers = await login(client, "core-error@example.com")
    conversation_id = await create_conversation(client, headers)
    generation_id = await submit_generation(client, headers, conversation_id)
    core = FakeCore()
    core.job_status = "error"
    core.job_error = "RuntimeError: /private/path/model.py failed\n--- log tail ---\nsecret prompt"
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(generation_id), db=db, client=core)
        generation = await db.get(Generation, uuid.UUID(generation_id))
        assert generation.status == "error"
        assert "/private" not in generation.error
        assert "secret prompt" not in generation.error


async def test_simulation_rejects_inconsistent_series(client):
    headers = await login(client, "bad-series@example.com")
    conversation_id = await create_conversation(client, headers)
    generation_id = await submit_generation(client, headers, conversation_id)
    core = FakeCore()
    async with SessionFactory() as db:
        await execute_generation(uuid.UUID(generation_id), db=db, client=core)
    generation = await client.get(f"/api/v1/generations/{generation_id}", headers=headers)
    version_id = generation.json()["model_version_id"]
    simulation = await client.post(
        f"/api/v1/model-versions/{version_id}/simulations",
        json={"parameters": {}},
        headers={**headers, "Idempotency-Key": "bad-series-key-1"},
    )
    simulation_id = simulation.json()["id"]
    core.result["variables"]["population"] = [100]
    async with SessionFactory() as db:
        await execute_simulation(uuid.UUID(simulation_id), db=db, client=core)
        stored = await db.get(Simulation, uuid.UUID(simulation_id))
        assert stored.status == "error"
        assert stored.result is None
        assert stored.error == "generator returned an invalid simulation result"


async def test_watchdog_recovers_lost_kick_and_stale_worker(client, monkeypatch):
    headers = await login(client, "watchdog@example.com")
    conversation_id = await create_conversation(client, headers)
    generation_id = await submit_generation(client, headers, conversation_id)
    kicked = []

    async def record_kick(resource_id):
        kicked.append(resource_id)

    monkeypatch.setattr("app.watchdog.kick_generation", record_kick)
    async with SessionFactory() as db:
        generation = await db.get(Generation, uuid.UUID(generation_id))
        generation.updated_at = utc_now() - timedelta(seconds=30)
        await db.commit()
    from app.watchdog import recover_jobs

    assert await recover_jobs() == (1, 0)
    assert kicked == [uuid.UUID(generation_id)]

    async with SessionFactory() as db:
        generation = await db.get(Generation, uuid.UUID(generation_id))
        generation.status = "running"
        generation.generator_job_id = "generation-job"
        generation.lease_expires_at = utc_now() - timedelta(seconds=1)
        await db.commit()
    assert await recover_jobs() == (1, 0)
    core = FakeCore()
    async with SessionFactory() as db:
        generation = await db.get(Generation, uuid.UUID(generation_id))
        assert generation.status == "queued"
        await execute_generation(generation.id, db=db, client=core)
        assert generation.status == "done"
    assert core.create_chat_calls == 0

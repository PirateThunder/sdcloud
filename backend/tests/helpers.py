from datetime import UTC, datetime

from httpx import AsyncClient

from app.clients.generator import CoreJobInfo
from app.generations.schemas import ModelDocumentSnapshot
from app.models.service import document_hash


async def login(client: AsyncClient, email: str = "user@example.com") -> dict[str, str]:
    requested = await client.post("/api/v1/auth/email/request", json={"email": email})
    assert requested.status_code == 202, requested.text
    code = requested.json()["dev_code"]
    verified = await client.post("/api/v1/auth/email/verify", json={"email": email, "code": code})
    assert verified.status_code == 200, verified.text
    return {
        "Authorization": f"Bearer {verified.json()['access_token']}",
        "user_id": verified.json()["user"]["id"],
    }


async def create_conversation(client: AsyncClient, headers: dict) -> str:
    response = await client.post("/api/v1/conversations", json={}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def model_document() -> dict:
    return {
        "schema_version": "2.0",
        "id": "population_model",
        "name": "Population",
        "description": "Exponential population growth",
        "time": {
            "unit": "year",
            "initial_time": 0,
            "final_time": 1,
            "time_step": 0.25,
            "saveper": 0.25,
        },
        "variables": [
            {
                "id": "population",
                "kind": "stock",
                "initial": {"op": "lit", "value": 100},
                "units": {"person": 1},
            },
            {
                "id": "growth",
                "kind": "flow",
                "expression": {
                    "op": "mul",
                    "args": [
                        {"op": "ref", "name": "population"},
                        {"op": "ref", "name": "growth_rate"},
                    ],
                },
                "source": {"kind": "cloud", "id": "growth_source"},
                "target": {"kind": "stock", "id": "population"},
                "units": {"person": 1, "year": -1},
            },
            {
                "id": "growth_rate",
                "kind": "constant",
                "expression": {"op": "lit", "value": 0.1},
                "units": {"year": -1},
            },
        ],
        "tables": [],
        "dimensions": [],
        "assumptions": [],
        "artifacts": {},
        "validation": {
            "status": "passed",
            "issues": [],
            "capabilities": {"supported": {}, "reasons": {}},
        },
        "assistant_text": "Created the population model.",
    }


def simulation_result(document: dict) -> dict:
    times = [0, 0.25, 0.5, 0.75, 1]
    population = [100 * 1.025**index for index in range(5)]
    return {
        "schema_version": "2.0",
        "model_id": document["id"],
        "model_hash": document_hash(
            ModelDocumentSnapshot.model_validate(document).model_dump(mode="json")
        ),
        "time": times,
        "variables": {
            "population": population,
            "growth": [value * 0.1 for value in population],
            "growth_rate": [0.1] * 5,
        },
        "requested_engine": "auto",
        "engine": "pysd",
        "requested_method": "euler",
        "integration_method": "euler",
        "time_step": 0.25,
        "saveper": 0.25,
        "fallback_reason": None,
        "warnings": [],
        "metadata": {"points": 5},
        "created_at": datetime.now(UTC).isoformat(),
    }


def core_job(job_id: str, kind: str, status: str = "done", error: str | None = None) -> CoreJobInfo:
    return CoreJobInfo(
        job_id=job_id,
        kind=kind,
        status=status,
        stage=status,
        attempt=1,
        created_at=datetime.now(UTC),
        files=["model.py", "model.mdl", "model.xmile"]
        if kind in {"generate", "chat"}
        else ["simulation.json"],
        manifest={"usage": {"tokens": 10}},
        error=error,
    )


class FakeCore:
    def __init__(
        self,
        document: dict | None = None,
        result: dict | None = None,
        response: dict | None = None,
    ) -> None:
        self.document = document or model_document()
        self.result = (
            result
            if result is not None
            else simulation_result(self.document)
            if {"id", "variables", "time"} <= self.document.keys()
            else {}
        )
        self.response = response or {
            "kind": "model",
            "assistant_text": self.document.get("assistant_text", "Model ready."),
            "model": self.document,
        }
        self.create_chat_calls = 0
        self.chat_payloads = []
        self.create_simulation_calls = 0
        self.job_status = "done"
        self.job_error = None

    async def create_chat(self, payload: dict, idempotency_key: str) -> str:
        self.create_chat_calls += 1
        self.chat_payloads.append(payload)
        return "generation-job"

    async def create_simulation(self, payload: dict, idempotency_key: str) -> str:
        self.create_simulation_calls += 1
        return "simulation-job"

    async def get_job(self, job_id: str) -> CoreJobInfo:
        kind = "chat" if job_id == "generation-job" else "simulate"
        return core_job(job_id, kind, self.job_status, self.job_error)

    async def get_result(self, job_id: str) -> dict:
        return self.response if job_id == "generation-job" else self.result

    async def download_text(self, job_id: str, filename: str) -> str:
        return f"generated {filename}"

    async def close(self) -> None:
        return None

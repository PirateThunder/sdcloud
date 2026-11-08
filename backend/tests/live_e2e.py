import argparse
import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx


class LiveE2E:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.client = httpx.AsyncClient(base_url=base_url, timeout=60)
        self.timeout_seconds = timeout_seconds
        self.steps: list[dict] = []
        self.checks: list[str] = []

    async def close(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, path: str, expected: int = 200, **kwargs) -> httpx.Response:
        started = time.monotonic()
        response = await self.client.request(method, path, **kwargs)
        self.steps.append(
            {
                "method": method,
                "path": path,
                "status": response.status_code,
                "duration_seconds": round(time.monotonic() - started, 3),
            }
        )
        if response.status_code != expected:
            raise RuntimeError(
                f"{method} {path}: expected {expected}, got {response.status_code}: "
                f"{response.text[:500]}"
            )
        return response

    def check(self, condition: bool, description: str) -> None:
        if not condition:
            raise AssertionError(description)
        self.checks.append(description)

    def headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def login(self, email: str) -> tuple[str, dict[str, str]]:
        requested = await self.call(
            "POST", "/api/v1/auth/email/request", expected=202, json={"email": email}
        )
        code = requested.json().get("dev_code")
        self.check(isinstance(code, str) and len(code) == 6, "local/test OTP is available")
        verified = await self.call(
            "POST",
            "/api/v1/auth/email/verify",
            json={"email": email, "code": code},
        )
        token = verified.json()["access_token"]
        return token, self.headers(token)

    async def wait_generation(self, generation_id: str, headers: dict[str, str]) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = await self.call(
                "GET", f"/api/v1/generations/{generation_id}", headers=headers
            )
            generation = response.json()
            if generation["status"] == "done":
                return generation
            if generation["status"] == "error":
                raise RuntimeError(f"generation failed: {generation.get('error')}")
            await asyncio.sleep(1)
        raise TimeoutError(f"generation {generation_id} did not finish")

    async def wait_simulation(self, simulation_id: str, headers: dict[str, str]) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = await self.call(
                "GET", f"/api/v1/simulations/{simulation_id}", headers=headers
            )
            simulation = response.json()
            if simulation["status"] == "done":
                return simulation
            if simulation["status"] == "error":
                raise RuntimeError(f"simulation failed: {simulation.get('error')}")
            await asyncio.sleep(1)
        raise TimeoutError(f"simulation {simulation_id} did not finish")

    async def send_message(
        self, conversation_id: str, content: str, headers: dict[str, str]
    ) -> tuple[dict, dict]:
        key = f"live-e2e-{uuid.uuid4()}"
        accepted = await self.call(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            expected=202,
            json={"content": content},
            headers={**headers, "Idempotency-Key": key},
        )
        generation_id = accepted.json()["generation_id"]
        generation = await self.wait_generation(generation_id, headers)
        replay = await self.call(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": content},
            headers={**headers, "Idempotency-Key": key},
        )
        self.check(replay.json()["generation_id"] == generation_id, "message replay is idempotent")
        return accepted.json(), generation

    async def run(self) -> dict:
        suffix = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        token, headers = await self.login(f"rest-e2e-{suffix}@example.com")
        me = await self.call("GET", "/api/v1/auth/me", headers=headers)
        self.check(me.json()["email"].endswith("@example.com"), "OTP identity is resolved")

        refreshed = await self.call("POST", "/api/v1/auth/refresh")
        token = refreshed.json()["access_token"]
        headers = self.headers(token)
        self.check(bool(token), "refresh session rotates the access token")

        created = await self.call(
            "POST",
            "/api/v1/conversations",
            expected=201,
            json={"title": "REST E2E"},
            headers=headers,
        )
        conversation_id = created.json()["id"]
        _, first_generation = await self.send_message(
            conversation_id, "Predator prey model with rabbits and foxes.", headers
        )
        first_version_id = first_generation["model_version_id"]
        self.check(bool(first_version_id), "first message creates a model version")
        first_version = (
            await self.call("GET", f"/api/v1/model-versions/{first_version_id}", headers=headers)
        ).json()
        model_id = first_version["model_id"]
        self.check(first_version["version"] == 1, "first model version is numbered one")

        _, answer_generation = await self.send_message(
            conversation_id, "What is the prey growth rate?", headers
        )
        self.check(answer_generation["model_version_id"] is None, "question answers in context")

        _, edit_generation = await self.send_message(
            conversation_id, "Set prey growth to 0.2", headers
        )
        second_version_id = edit_generation["model_version_id"]
        self.check(
            bool(second_version_id) and second_version_id != first_version_id,
            "edit creates a new model version",
        )
        second_version = (
            await self.call("GET", f"/api/v1/model-versions/{second_version_id}", headers=headers)
        ).json()
        self.check(second_version["model_id"] == model_id, "versions belong to one model")
        self.check(second_version["version"] == 2, "edit increments the model version")

        messages = (
            await self.call(
                "GET", f"/api/v1/conversations/{conversation_id}/messages", headers=headers
            )
        ).json()
        self.check(len(messages) == 6, "three turns produce six ordered messages")
        self.check(
            [message["role"] for message in messages]
            == ["user", "assistant", "user", "assistant", "user", "assistant"],
            "messages retain user/assistant order",
        )
        self.check(
            all(message["status"] == "done" for message in messages),
            "all messages reach done status",
        )
        self.check(
            [message["content"] for message in messages][0::2]
            == [
                "Predator prey model with rabbits and foxes.",
                "What is the prey growth rate?",
                "Set prey growth to 0.2",
            ],
            "message content remains attached to the correct turn",
        )
        self.check(
            messages[1]["model_version_id"] == first_version_id
            and messages[3]["model_version_id"] is None
            and messages[5]["model_version_id"] == second_version_id,
            "message version links match generation results",
        )

        simulation_created = await self.call(
            "POST",
            f"/api/v1/model-versions/{second_version_id}/simulations",
            expected=202,
            json={
                "parameters": {
                    "integration_method": "euler",
                    "final_time": 1,
                    "time_step": 0.25,
                    "saveper": 0.25,
                }
            },
            headers={**headers, "Idempotency-Key": f"live-e2e-{uuid.uuid4()}"},
        )
        simulation_id = simulation_created.json()["id"]
        simulation = await self.wait_simulation(simulation_id, headers)
        result = simulation["result"]
        self.check(result["time"][-1] == 1, "simulation reaches the requested horizon")
        self.check(
            all(len(series) == len(result["time"]) for series in result["variables"].values()),
            "simulation series share one time grid",
        )

        versions = (
            await self.call("GET", f"/api/v1/models/{model_id}/versions", headers=headers)
        ).json()
        self.check(versions["total"] == 2, "model history contains exactly two versions")
        for export_format, marker in (("python", "def"), ("vensim", "|"), ("xmile", "<xmile")):
            exported = await self.call(
                "GET",
                f"/api/v1/models/{model_id}/versions/2/export",
                params={"format": export_format},
                headers=headers,
            )
            self.check(marker in exported.text, f"{export_format} export has expected content")
            self.check(
                "attachment" in exported.headers.get("content-disposition", ""),
                f"{export_format} export is downloadable",
            )

        _, other_headers = await self.login(f"rest-e2e-other-{suffix}@example.com")
        for path in (
            f"/api/v1/conversations/{conversation_id}",
            f"/api/v1/model-versions/{second_version_id}",
            f"/api/v1/simulations/{simulation_id}",
        ):
            await self.call("GET", path, expected=404, headers=other_headers)
        self.checks.append("another user cannot access conversation, version or simulation")

        return {
            "conversation_id": conversation_id,
            "model_id": model_id,
            "version_ids": [first_version_id, second_version_id],
            "simulation_id": simulation_id,
        }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the public REST product E2E against local/test")
    parser.add_argument(
        "--base-url", default=os.environ.get("BACKEND_URL", "http://127.0.0.1:61231")
    )
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = {
        "schema_version": "1.0",
        "kind": "rest_product_e2e",
        "base_url": args.base_url,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
    }
    runner = LiveE2E(args.base_url, args.timeout_seconds)
    try:
        resources = await runner.run()
        report.update(status="passed", resources=resources)
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        await runner.close()
        report["steps"] = runner.steps
        report["checks"] = runner.checks
        report["finished_at"] = datetime.now(UTC).isoformat()
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    print(
        f"REST E2E: {report['status']}; steps={len(runner.steps)}; checks={len(runner.checks)}"
    )
    if args.output is not None:
        print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

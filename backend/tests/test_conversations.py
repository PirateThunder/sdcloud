import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.conversations.models import Message
from app.database import SessionFactory
from app.generations.models import Generation
from tests.helpers import create_conversation, login


async def test_conversation_message_idempotency_and_ownership(client):
    headers = await login(client, "owner@example.com")
    conversation_id = await create_conversation(client, headers)
    payload = {"content": "Population grows at 10 percent per year"}

    created = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json=payload,
        headers={**headers, "Idempotency-Key": "message-key-1"},
    )
    assert created.status_code == 202, created.text
    generation_id = created.json()["generation_id"]
    assert created.json()["assistant_message"]["status"] == "queued"

    replay = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json=payload,
        headers={**headers, "Idempotency-Key": "message-key-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["generation_id"] == generation_id

    conflict = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Different request"},
        headers={**headers, "Idempotency-Key": "message-key-1"},
    )
    assert conflict.status_code == 409

    messages = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=headers
    )
    assert len(messages.json()) == 2
    generation = await client.get(f"/api/v1/generations/{generation_id}", headers=headers)
    assert generation.status_code == 200
    assert "generator_job_id" not in generation.json()

    other_headers = await login(client, "other@example.com")
    assert (
        await client.get(f"/api/v1/conversations/{conversation_id}", headers=other_headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/generations/{generation_id}", headers=other_headers)
    ).status_code == 404


async def test_idempotency_key_cannot_be_reused_in_another_conversation(client):
    headers = await login(client, "scope@example.com")
    first = await create_conversation(client, headers)
    second = await create_conversation(client, headers)
    request = {
        "json": {"content": "Same text"},
        "headers": {**headers, "Idempotency-Key": "shared-key-1"},
    }
    assert (
        await client.post(f"/api/v1/conversations/{first}/messages", **request)
    ).status_code == 202
    assert (
        await client.post(f"/api/v1/conversations/{second}/messages", **request)
    ).status_code == 409


async def test_equal_timestamps_keep_user_before_assistant(client):
    headers = await login(client, "ordering@example.com")
    conversation_id = await create_conversation(client, headers)
    timestamp = datetime.now(UTC)
    async with SessionFactory() as db:
        db.add_all(
            [
                Message(
                    id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                    conversation_id=uuid.UUID(conversation_id),
                    role="user",
                    content="question",
                    created_at=timestamp,
                ),
                Message(
                    id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                    conversation_id=uuid.UUID(conversation_id),
                    role="assistant",
                    content="answer",
                    created_at=timestamp,
                ),
            ]
        )
        await db.commit()

    response = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=headers
    )
    assert response.status_code == 200, response.text
    assert [message["role"] for message in response.json()] == ["user", "assistant"]
    assert [message["content"] for message in response.json()] == ["question", "answer"]


async def test_conversation_crud_and_cascade(client):
    headers = await login(client, "crud@example.com")
    conversation_id = await create_conversation(client, headers)
    updated = await client.patch(
        f"/api/v1/conversations/{conversation_id}", json={"title": "System model"}, headers=headers
    )
    assert updated.json()["title"] == "System model"
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Inventory model"},
        headers={**headers, "Idempotency-Key": "delete-key-1"},
    )
    assert (
        await client.delete(f"/api/v1/conversations/{conversation_id}", headers=headers)
    ).status_code == 204
    async with SessionFactory() as db:
        assert await db.scalar(select(func.count(Message.id))) == 0
        assert await db.scalar(select(func.count(Generation.id))) == 0

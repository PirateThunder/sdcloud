"""Taskiq background tasks for sdCloud."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.generated_model import GeneratedModel
from app.models.message import Message
from app.services.generation import generate_model_from_description

logger = logging.getLogger(__name__)


async def generate_model_task(
    conversation_id: str,
    message_id: str,
    user_description: str,
) -> dict:
    """
    Background task for AI model generation pipeline.

    Pipeline stages:
    1. Extract variables from user description via LLM
    2. Build CLD (Causal Loop Diagram)
    3. Validate CLD graph
    4. Generate equations
    5. Build SFD (Stock-Flow Diagram)
    6. Generate Python code for PySD
    7. Generate Vensim code
    8. Save results to database

    Args:
        conversation_id: UUID of the conversation.
        message_id: UUID of the assistant message to update.
        user_description: User's system description text.

    Returns:
        dict with generation results.
    """
    conv_id = UUID(conversation_id)
    msg_id = UUID(message_id)

    async with AsyncSessionLocal() as db:
        try:
            # Create GeneratedModel record with "generating" status
            gen_model = GeneratedModel(
                message_id=msg_id,
                conversation_id=conv_id,
                name=f"Model for {user_description[:50]}",
                variables=[],
                equations=[],
                cld_data={},
                sfd_data={},
                status="generating",
            )
            db.add(gen_model)
            await db.commit()
            await db.refresh(gen_model)

            # Run the pure generation pipeline
            generation_result = await generate_model_from_description(user_description)

            if generation_result["status"] == "error":
                gen_model.status = "error"
                await db.commit()
                return {
                    "status": "error",
                    "error": generation_result.get("error", "Unknown error"),
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                }

            # Update the GeneratedModel record
            gen_model.variables = generation_result["variables"]
            gen_model.equations = generation_result["equations"]
            gen_model.cld_data = generation_result["cld_data"]
            gen_model.sfd_data = generation_result["sfd_data"]
            gen_model.python_code = generation_result["python_code"]
            gen_model.vensim_code = generation_result["vensim_code"]
            gen_model.status = "completed"

            # Update the assistant message with model metadata
            message_result = await db.execute(select(Message).where(Message.id == msg_id))
            message = message_result.scalar_one_or_none()
            if message:
                message.model_metadata = {
                    "generation_log": generation_result["log"],
                    "model_id": str(gen_model.id),
                    "variables_count": len(generation_result["variables"]),
                    "equations_count": len(generation_result["equations"]),
                    "cld_valid": generation_result["cld_data"]["validation"]["valid"],
                    "sfd_valid": generation_result["sfd_data"]["validation"]["valid"],
                    "feedback_loops": generation_result["cld_data"]["validation"].get("feedback_loops", []),
                }

            await db.commit()
            generation_result["log"].append("  Results saved successfully")

            return {
                "status": "completed",
                "model_id": str(gen_model.id),
                "variables_count": len(generation_result["variables"]),
                "equations_count": len(generation_result["equations"]),
                "cld_valid": generation_result["cld_data"]["validation"]["valid"],
                "sfd_valid": generation_result["sfd_data"]["validation"]["valid"],
                "log": generation_result["log"],
            }

        except Exception as exc:
            logger.exception(f"Model generation task failed: {exc}")

            # Update status to error
            try:
                gen_model_result = await db.execute(
                    select(GeneratedModel).where(
                        GeneratedModel.message_id == msg_id
                    )
                )
                gen_model = gen_model_result.scalar_one_or_none()
                if gen_model:
                    gen_model.status = "error"
                    await db.commit()
            except Exception:
                pass

            # Update message
            try:
                message_result = await db.execute(select(Message).where(Message.id == msg_id))
                message = message_result.scalar_one_or_none()
                if message:
                    message.model_metadata = {"error": str(exc)}
                    await db.commit()
            except Exception:
                pass

            return {
                "status": "error",
                "error": str(exc),
                "conversation_id": conversation_id,
                "message_id": message_id,
            }

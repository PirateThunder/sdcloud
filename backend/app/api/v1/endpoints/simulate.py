"""Simulation endpoints for running PySD simulations on generated models."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError, SimulationError, ValidationError
from app.models.conversation import Conversation
from app.models.generated_model import GeneratedModel
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.simulation import (
    SimulationResponse,
    SimulationRunRequest,
)
from app.services.simulation.pysd_runner import PySDRunner

router = APIRouter(prefix="/models", tags=["Simulations"])


@router.post(
    "/{model_id}/simulate",
    response_model=SimulationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run simulation on a generated model",
)
async def run_simulation(
    model_id: UUID,
    data: SimulationRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Simulation:
    """
    Run a PySD simulation on a generated model.

    If the model has Python code, it will be used directly.
    Otherwise, Vensim code will be used as a fallback.
    """
    # Get the model
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    # Verify ownership through conversation
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    # Check model has code
    if not model.python_code and not model.vensim_code:
        raise ValidationError(
            detail="Model has no executable code. Generation may still be in progress."
        )

    # Create simulation record
    simulation = Simulation(
        model_id=model_id,
        parameters=data.parameters.custom_params,
        time_start=data.parameters.time_start,
        time_end=data.parameters.time_end,
        time_step=data.parameters.time_step,
        status="running",
    )
    db.add(simulation)
    await db.commit()
    await db.refresh(simulation)

    try:
        # Run the simulation
        runner = PySDRunner()

        if model.python_code:
            results = await runner.simulate_from_python(
                python_code=model.python_code,
                params=data.parameters.custom_params,
                time_start=data.parameters.time_start,
                time_end=data.parameters.time_end,
                time_step=data.parameters.time_step,
            )
        elif model.vensim_code:
            results = await runner.simulate_from_vensim(
                vensim_code=model.vensim_code,
                params=data.parameters.custom_params,
                time_start=data.parameters.time_start,
                time_end=data.parameters.time_end,
                time_step=data.parameters.time_step,
            )
        else:
            raise SimulationError(detail="No model code available")

        # Update simulation with results
        simulation.results = results
        simulation.status = "completed"
        simulation.completed_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(simulation)

        # Cleanup runner temp files
        runner.cleanup()

        return simulation

    except Exception as exc:
        simulation.status = "error"
        simulation.results = {"error": str(exc)}
        simulation.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(simulation)
        raise SimulationError(detail=f"Simulation failed: {str(exc)}")


@router.get(
    "/simulations/{simulation_id}",
    response_model=SimulationResponse,
    summary="Get simulation results",
)
async def get_simulation(
    simulation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Simulation:
    """Return the results of a simulation run."""
    result = await db.execute(
        select(Simulation)
        .where(Simulation.id == simulation_id)
    )
    simulation = result.scalar_one_or_none()

    if simulation is None:
        raise NotFoundError(detail="Simulation not found")

    # Verify ownership through the model -> conversation chain
    model_result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == simulation.model_id)
    )
    model = model_result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Associated model not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Simulation not found")

    return simulation


@router.get(
    "/{model_id}/simulations",
    summary="List simulations for a model",
)
async def list_simulations(
    model_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all simulation runs for a given model."""
    # Verify model ownership
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    sim_result = await db.execute(
        select(Simulation)
        .where(Simulation.model_id == model_id)
        .order_by(Simulation.created_at.desc())
    )
    simulations = sim_result.scalars().all()

    return {
        "items": [
            {
                "id": str(sim.id),
                "model_id": str(sim.model_id),
                "parameters": sim.parameters,
                "time_start": sim.time_start,
                "time_end": sim.time_end,
                "time_step": sim.time_step,
                "results": sim.results,
                "status": sim.status,
                "created_at": sim.created_at.isoformat(),
                "completed_at": sim.completed_at.isoformat() if sim.completed_at else None,
            }
            for sim in simulations
        ],
        "total": len(simulations),
    }

from .schemas import ModelDocument
from .validation import ensure_valid_model, validate_model


def validate_model_equations(document: ModelDocument) -> ModelDocument:
    return ensure_valid_model(document)


__all__ = ["ensure_valid_model", "validate_model", "validate_model_equations"]

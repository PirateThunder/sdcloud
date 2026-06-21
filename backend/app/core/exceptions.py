"""Custom exceptions and error handling for the application."""

from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: dict | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class AuthenticationError(AppException):
    """Raised when authentication fails."""

    def __init__(self, detail: str = "Authentication failed") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class AuthorizationError(AppException):
    """Raised when user is not authorized to access a resource."""

    def __init__(self, detail: str = "Not authorized") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class NotFoundError(AppException):
    """Raised when a requested resource is not found."""

    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )


class ConflictError(AppException):
    """Raised when there is a conflict with the current state."""

    def __init__(self, detail: str = "Resource already exists") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


class ValidationError(AppException):
    """Raised when input validation fails."""

    def __init__(self, detail: str = "Validation error") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )


class LLMError(AppException):
    """Raised when LLM API call fails."""

    def __init__(self, detail: str = "LLM service error") -> None:
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class SimulationError(AppException):
    """Raised when simulation fails."""

    def __init__(self, detail: str = "Simulation error") -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


class GraphValidationError(AppException):
    """Raised when graph validation fails."""

    def __init__(self, detail: str = "Graph validation error") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )

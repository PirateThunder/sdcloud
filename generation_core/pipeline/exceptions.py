class EngineError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class LLMError(EngineError):
    pass


class ModelValidationError(EngineError):
    pass


class SimulationError(EngineError):
    pass

class EngineError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class LLMError(EngineError):
    pass


class LLMResponseError(LLMError):
    def __init__(self, detail: str, *, response_text: str = "") -> None:
        super().__init__(detail)
        self.response_text = response_text


class ModelValidationError(EngineError):
    pass


class SimulationError(EngineError):
    pass

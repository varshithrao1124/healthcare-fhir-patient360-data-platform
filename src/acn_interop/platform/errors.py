"""Exceptions that mark which lane of the pipeline failed."""


class AlderbrookError(Exception):
    """Base error for Alderbrook Interop."""


class ConfigError(AlderbrookError):
    """Raised when required configuration or a secret reference is missing."""


class ContractError(AlderbrookError):
    """Raised when a payload breaks a published contract."""


class ParseError(AlderbrookError):
    """Raised when an HL7 or FHIR payload cannot be interpreted."""


class PipelineError(AlderbrookError):
    """Raised when a pipeline stage fails after retries."""

    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"{stage}: {message}")

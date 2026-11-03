"""Exceptions that mark which lane of the pipeline failed."""


class NorthlineError(Exception):
    """Base error for Northline."""


class ConfigError(NorthlineError):
    """Raised when required configuration or a secret reference is missing."""


class ContractError(NorthlineError):
    """Raised when a payload breaks a published contract."""


class ParseError(NorthlineError):
    """Raised when an HL7 or FHIR payload cannot be interpreted."""


class PipelineError(NorthlineError):
    """Raised when a pipeline stage fails after retries."""

    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"{stage}: {message}")

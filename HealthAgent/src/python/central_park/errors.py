"""Explicit failures for model-backed and clinical-context operations."""


class ModelServiceError(RuntimeError):
    """The model provider could not complete a request."""


class ModelOutputError(RuntimeError):
    """The model returned data that does not satisfy the required contract."""


class ClinicalContextError(RuntimeError):
    """A required clinical record could not be read reliably."""

class ApproveError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class AlreadyRegisteredError(ApproveError):
    """Raised when a model is registered for the approval workflow more than once."""


class ConflictError(ApproveError):
    """Target's current value no longer matches the request's old_value."""


class SelfApprovalError(ApproveError):
    """Reviewer is the same user who requested the change (four-eyes violation)."""

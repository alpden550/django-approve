class ApproveError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class AlreadyRegisteredError(ApproveError):
    """Raised when a model is registered for the approval workflow more than once."""

class ServiceError(ValueError):
    """An actionable error safe to display without provider credentials."""

    def __init__(self, message: str, *, retryable: bool = False, ambiguous: bool = False,
                 reconnect_required: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.ambiguous = ambiguous
        self.reconnect_required = reconnect_required

class NotFoundError(Exception):
    """A requested resource doesn't exist; the API responds 404."""


class RuleViolationError(Exception):
    """The request breaks a library rule; the API responds 422."""

class SemanticDbError(Exception):
    """Base for every error the CLI is expected to render as a message."""


class SchemaError(SemanticDbError):
    """A field or collection definition is not valid."""


class CollectionNotFoundError(SemanticDbError):
    def __init__(self, name: str) -> None:
        super().__init__(f"collection '{name}' does not exist")
        self.name = name


class DuplicateCollectionError(SemanticDbError):
    def __init__(self, name: str) -> None:
        super().__init__(f"collection '{name}' already exists")
        self.name = name


class PayloadError(SemanticDbError):
    """Base for payload problems; always names the offending field."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


class UnknownFieldError(PayloadError):
    def __init__(self, field: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"unknown field '{field}'; collection declares: {', '.join(known)}",
            field,
        )
        self.known = known


class MissingRequiredFieldError(PayloadError):
    def __init__(self, field: str) -> None:
        super().__init__(f"field '{field}' is required", field)


class PayloadValidationError(PayloadError):
    """A value could not be coerced into the field's declared type."""

    def __init__(self, field: str, declared_type: str, value: object, detail: str = "") -> None:
        message = f"field '{field}' expects {declared_type}, got {value!r}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message, field)
        self.declared_type = declared_type
        self.value = value


class EmbeddingUnavailableError(SemanticDbError):
    """The embedding provider could not be reached or answered unusably."""

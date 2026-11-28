class AgentError(Exception):
    """Base class for everything the agent raises on purpose."""


class LLMUnavailable(AgentError):
    """The language model didn't answer (down, timeout, error status)."""


class DatabaseUnavailable(AgentError):
    """No database connection could be obtained."""


class UnsafeQuery(AgentError):
    """The model's SQL was refused before reaching the database."""


class QueryTimeout(AgentError):
    """The database stopped the query (statement_timeout)."""


class QueryFailed(AgentError):
    """The database rejected the query, e.g. an unknown column. The message helps the model fix it."""

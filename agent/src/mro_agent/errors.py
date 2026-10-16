"""Domain errors returned as safe tool responses."""


class AgentError(Exception):
    """Base class for expected agent/tool failures."""


class ValidationError(AgentError):
    """An input or experiment plan is not valid for an approved profile."""


class NotFoundError(AgentError):
    """A requested dataset, profile, or plan is not registered."""


class ConfigurationError(AgentError):
    """Required protected deployment configuration is unavailable."""


class BrainAPIError(AgentError):
    """CloudMR Brain returned an unsuccessful API response."""

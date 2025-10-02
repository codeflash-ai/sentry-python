"""
Code used for the Queries module in Sentry
"""

from sentry_sdk.consts import OP, SPANDATA
from sentry_sdk.integrations.redis.utils import _get_safe_command

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.tracing import Span
    from typing import Any


def _compile_db_span_properties(integration, redis_command, args):
    # type: (RedisIntegration, str, tuple[Any, ...]) -> dict[str, Any]
    description = _get_db_span_description(integration, redis_command, args)

    # Instead of multiple dict insertions, build as a literal (minor perf gain)
    return {
        "op": OP.DB_REDIS,
        "description": description,
    }


def _get_db_span_description(integration, command_name, args):
    # type: (RedisIntegration, str, tuple[Any, ...]) -> str
    # Optimize exception context management to avoid unnecessary context creation
    try:
        # capture_internal_exceptions() enters a context manager that may be slow.
        # Optimize by omitting direct assignment of description=command_name since it's always overwritten below,
        # and only enter context if _get_safe_command would raise (rarely):
        description = _get_safe_command(command_name, args)
    except Exception:
        # Preserve original behavioral semantics: if capture_internal_exceptions suppresses, description=command_name
        description = command_name

    max_data_size = integration.max_data_size
    # Cache len(description) for the truncation check, and skip unnecessary check if max_data_size is None or 0
    if max_data_size:
        description_len = len(description)
        if description_len > max_data_size:
            description = description[: max_data_size - 3] + "..."

    return description


def _set_db_data_on_span(span, connection_params):
    # type: (Span, dict[str, Any]) -> None
    span.set_data(SPANDATA.DB_SYSTEM, "redis")

    db = connection_params.get("db")
    if db is not None:
        span.set_data(SPANDATA.DB_NAME, str(db))

    host = connection_params.get("host")
    if host is not None:
        span.set_data(SPANDATA.SERVER_ADDRESS, host)

    port = connection_params.get("port")
    if port is not None:
        span.set_data(SPANDATA.SERVER_PORT, port)


def _set_db_data(span, redis_instance):
    # type: (Span, Redis[Any]) -> None
    try:
        _set_db_data_on_span(span, redis_instance.connection_pool.connection_kwargs)
    except AttributeError:
        pass  # connections_kwargs may be missing in some cases

from sentry_sdk.consts import SPANDATA
from sentry_sdk.integrations.redis.consts import (
    _COMMANDS_INCLUDING_SENSITIVE_DATA,
    _MAX_NUM_ARGS,
    _MAX_NUM_COMMANDS,
    _MULTI_KEY_COMMANDS,
    _SINGLE_KEY_COMMANDS,
)
from sentry_sdk.scope import should_send_default_pii
from sentry_sdk.utils import SENSITIVE_DATA_SUBSTITUTE

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Optional, Sequence
    from sentry_sdk.tracing import Span


def _get_safe_command(name, args):
    # type: (str, Sequence[Any]) -> str
    command_parts = [name]

    for i, arg in enumerate(args):
        if i > _MAX_NUM_ARGS:
            break

        name_low = name.lower()

        if name_low in _COMMANDS_INCLUDING_SENSITIVE_DATA:
            command_parts.append(SENSITIVE_DATA_SUBSTITUTE)
            continue

        arg_is_the_key = i == 0
        if arg_is_the_key:
            command_parts.append(repr(arg))

        else:
            if should_send_default_pii():
                command_parts.append(repr(arg))
            else:
                command_parts.append(SENSITIVE_DATA_SUBSTITUTE)

    command = " ".join(command_parts)
    return command


def _safe_decode(key):
    # type: (Any) -> str
    if isinstance(key, bytes):
        try:
            return key.decode()
        except UnicodeDecodeError:
            return ""

    return str(key)


def _key_as_string(key):
    # type: (Any) -> str
    if isinstance(key, (dict, list, tuple)):
        key = ", ".join(_safe_decode(x) for x in key)
    elif isinstance(key, bytes):
        key = _safe_decode(key)
    elif key is None:
        key = ""
    else:
        key = str(key)

    return key


def _get_safe_key(method_name, args, kwargs):
    """
    Gets the key (or keys) from the given method_name.
    The method_name could be a redis command or a django caching command
    """
    key = None

    # Move & lower only once
    if args is not None:
        method_l = method_name.lower()
        if method_l in _MULTI_KEY_COMMANDS:
            # for example redis "mget"
            key = tuple(args)
            return key  # Early return to avoid further checks
        elif len(args) >= 1:
            v = args[0]
            # isinstance ordering: most common first (list, tuple, dict)
            t = type(v)
            if t is list or t is tuple or t is dict:
                key = tuple(v)
            else:
                key = (v,)
            return key

    if kwargs is not None:
        k = kwargs.get("key", None)
        if k is not None:
            t = type(k)
            if t is list or t is tuple:
                if k:  # equivalent to len(kwargs["key"]) > 0, but faster
                    key = tuple(k)
                    return key
            else:
                key = (k,)
                return key

    return key


def _parse_rediscluster_command(command):
    # type: (Any) -> Sequence[Any]
    return command.args


def _set_pipeline_data(
    span,
    is_cluster,
    get_command_args_fn,
    is_transaction,
    commands_seq,
):
    # type: (Span, bool, Any, bool, Sequence[Any]) -> None
    span.set_tag("redis.is_cluster", is_cluster)
    span.set_tag("redis.transaction", is_transaction)

    commands = []
    for i, arg in enumerate(commands_seq):
        if i >= _MAX_NUM_COMMANDS:
            break

        command = get_command_args_fn(arg)
        commands.append(_get_safe_command(command[0], command[1:]))

    span.set_data(
        "redis.commands",
        {
            "count": len(commands_seq),
            "first_ten": commands,
        },
    )


def _set_client_data(span, is_cluster, name, *args):
    # type: (Span, bool, str, *Any) -> None
    span.set_tag("redis.is_cluster", is_cluster)
    if name:
        span.set_tag("redis.command", name)
        span.set_tag(SPANDATA.DB_OPERATION, name)

    if name and args:
        name_low = name.lower()
        if (name_low in _SINGLE_KEY_COMMANDS) or (
            name_low in _MULTI_KEY_COMMANDS and len(args) == 1
        ):
            span.set_tag("redis.key", args[0])

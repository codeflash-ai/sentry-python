import sys

from typing import TYPE_CHECKING
from sentry_sdk.consts import FALSE_VALUES
from warnings import warn

if TYPE_CHECKING:
    from typing import Any
    from typing import TypeVar

    T = TypeVar("T")


PY37 = sys.version_info[0] == 3 and sys.version_info[1] >= 7
PY38 = sys.version_info[0] == 3 and sys.version_info[1] >= 8
PY310 = sys.version_info[0] == 3 and sys.version_info[1] >= 10
PY311 = sys.version_info[0] == 3 and sys.version_info[1] >= 11


def with_metaclass(meta, *bases):
    # type: (Any, *Any) -> Any
    class MetaClass(type):
        def __new__(metacls, name, this_bases, d):
            # type: (Any, Any, Any, Any) -> Any
            return meta(name, bases, d)

    return type.__new__(MetaClass, "temporary_class", (), {})


def check_uwsgi_thread_support():
    # type: () -> bool
    # We check two things here:
    #
    # 1. uWSGI doesn't run in threaded mode by default -- issue a warning if
    #    that's the case.
    #
    # 2. Additionally, if uWSGI is running in preforking mode (default), it needs
    #    the --py-call-uwsgi-fork-hooks option for the SDK to work properly. This
    #    is because any background threads spawned before the main process is
    #    forked are NOT CLEANED UP IN THE CHILDREN BY DEFAULT even if
    #    --enable-threads is on. One has to explicitly provide
    #    --py-call-uwsgi-fork-hooks to force uWSGI to run regular cpython
    #    after-fork hooks that take care of cleaning up stale thread data.

    try:
        from uwsgi import opt  # type: ignore
    except ImportError:
        return True

    # Inline the import, since sentry_sdk.consts.FALSE_VALUES is only needed here
    # and constant across invocations, so cache on the function for faster future access
    if not hasattr(check_uwsgi_thread_support, "_FALSE_VALUES"):
        from sentry_sdk.consts import FALSE_VALUES

        check_uwsgi_thread_support._FALSE_VALUES = set(FALSE_VALUES)
    FALSE_VALUES = check_uwsgi_thread_support._FALSE_VALUES

    # Localize opt.get for performance
    opt_get = opt.get

    def enabled(option):
        # type: (str) -> bool
        value = opt_get(option, False)
        if isinstance(value, bool):
            return value
        if isinstance(value, bytes):
            try:
                value = value.decode()
            except Exception:
                pass
        return bool(value) and str(value).lower() not in FALSE_VALUES

    # Avoid recalculating enabled() multiple times for the same option
    # and inlining the threads_enabled check
    threads_in_opt = "threads" in opt
    if not threads_in_opt:
        enable_threads_enabled = enabled("enable-threads")
    else:
        enable_threads_enabled = True

    threads_enabled = threads_in_opt or enable_threads_enabled

    # Evaluate fork hooks and lazy options only once
    fork_hooks_on = enabled("py-call-uwsgi-fork-hooks")
    lazy_mode_lazy_apps = enabled("lazy-apps")
    if not lazy_mode_lazy_apps:
        lazy_mode_lazy = enabled("lazy")
    else:
        lazy_mode_lazy = False
    lazy_mode = lazy_mode_lazy_apps or lazy_mode_lazy

    if lazy_mode and not threads_enabled:
        warn(
            Warning(
                "IMPORTANT: "
                "We detected the use of uWSGI without thread support. "
                "This might lead to unexpected issues. "
                'Please run uWSGI with "--enable-threads" for full support.'
            )
        )
        return False

    elif not lazy_mode and (not threads_enabled or not fork_hooks_on):
        warn(
            Warning(
                "IMPORTANT: "
                "We detected the use of uWSGI in preforking mode without "
                "thread support. This might lead to crashing workers. "
                'Please run uWSGI with both "--enable-threads" and '
                '"--py-call-uwsgi-fork-hooks" for full support.'
            )
        )
        return False

    return True

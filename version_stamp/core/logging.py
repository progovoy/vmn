#!/usr/bin/env python3
import logging
import sys
import threading
import time
from functools import wraps
from logging.handlers import RotatingFileHandler

from version_stamp.core.constants import (
    BOLD_CHAR,
    END_CHAR,
    GLOBAL_LOG_FILENAME,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    VMN_USER_NAME,
)

# ── Global logger ────────────────────────────────────────────────────

class _LoggerProxy:
    """Thin proxy so ``from ... import VMN_LOGGER`` always sees the live logger.

    When tests set ``stamp_utils.VMN_LOGGER = None`` we route that through
    __setattr__ on the shim module, which updates ``_logger_holder[0]``.
    Every module that imported VMN_LOGGER got *this* proxy object, so attribute
    access like ``VMN_LOGGER.info(...)`` is always forwarded to the real logger.
    """

    def __getattr__(self, name):
        target = _logger_holder[0]
        if target is None:
            raise AttributeError(
                f"VMN_LOGGER is not initialized (call init_stamp_logger first)"
            )
        return getattr(target, name)

    def __bool__(self):
        return _logger_holder[0] is not None

    def __repr__(self):
        return f"<_LoggerProxy wrapping {_logger_holder[0]!r}>"


_logger_holder = [None]
VMN_LOGGER = _LoggerProxy()


# ── Thread-local runtime context (ARCH-4 fix) ───────────────────────

class _RuntimeContext(threading.local):
    def __init__(self):
        super().__init__()
        self.call_stack = []
        self.call_count = {}


_runtime_ctx = _RuntimeContext()


def reset_runtime_context():
    """Reset thread-local call tracking state. Useful in test fixtures."""
    _runtime_ctx.call_stack = []
    _runtime_ctx.call_count = {}


def get_call_stack():
    """Return the current thread's call stack."""
    return _runtime_ctx.call_stack


# ── Decorator ────────────────────────────────────────────────────────

def measure_runtime_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        ctx = _runtime_ctx

        if func.__name__ not in ctx.call_count:
            ctx.call_count[func.__name__] = 0
        ctx.call_count[func.__name__] += 1

        ctx.call_stack.append(func.__name__)
        fcode = func.__code__

        if VMN_LOGGER:
            VMN_LOGGER.debug(
                f"{'  ' * (len(ctx.call_stack) - 1)}--> Entering {func.__name__} at {fcode.co_filename}:{fcode.co_firstlineno}"
            )

        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()

        elapsed_time = end_time - start_time

        if VMN_LOGGER:
            VMN_LOGGER.debug(
                f"{'  ' * (len(ctx.call_stack) - 1)}<-- Exiting {func.__name__} {BOLD_CHAR} took {elapsed_time:.6f} seconds {END_CHAR} at {fcode.co_filename}:{fcode.co_firstlineno}"
            )

        ctx.call_stack.pop()

        return result

    return wrapper


# ── Logger filter ────────────────────────────────────────────────────

class LevelFilter(logging.Filter):
    def __init__(self, low, high):
        self._low = low
        self._high = high
        logging.Filter.__init__(self)

    def filter(self, record):
        if self._low <= record.levelno <= self._high:
            return True
        return False


# ── Logger setup ─────────────────────────────────────────────────────

def init_stamp_logger(rotating_log_path=None, debug=False, supress_stdout=False):
    import os

    _logger_holder[0] = logging.getLogger(VMN_USER_NAME)
    clear_logger_handlers(VMN_LOGGER)
    glob_logger = logging.getLogger()
    clear_logger_handlers(glob_logger)

    glob_logger.setLevel(logging.DEBUG)
    logging.getLogger("git").setLevel(logging.WARNING)

    fmt = "[%(levelname)s] %(message)s"
    formatter = logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    min_stdout_level = logging.INFO
    if debug:
        min_stdout_level = logging.DEBUG

    stdout_handler.addFilter(LevelFilter(min_stdout_level, logging.INFO))

    if not supress_stdout or debug:
        VMN_LOGGER.addHandler(stdout_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)
    VMN_LOGGER.addHandler(stderr_handler)

    if rotating_log_path is None:
        return

    rotating_file_handler = init_log_file_handler(rotating_log_path)
    VMN_LOGGER.addHandler(rotating_file_handler)

    global_log_path = os.path.join(
        os.path.dirname(rotating_log_path), GLOBAL_LOG_FILENAME
    )
    global_file_handler = init_log_file_handler(global_log_path)
    glob_logger.addHandler(global_file_handler)


def init_log_file_handler(rotating_log_path):
    rotating_file_handler = RotatingFileHandler(
        rotating_log_path,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
    )
    rotating_file_handler.setLevel(logging.DEBUG)
    fmt = "[%(levelname)s] %(asctime)s %(pathname)s:%(lineno)d =>\n%(message)s"
    formatter = logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S")
    rotating_file_handler.setFormatter(formatter)
    return rotating_file_handler


def clear_logger_handlers(logger_obj):
    hlen = len(logger_obj.handlers)
    for h in range(hlen):
        logger_obj.handlers[0].close()
        logger_obj.removeHandler(logger_obj.handlers[0])
    flen = len(logger_obj.filters)
    for f in range(flen):
        logger_obj.removeFilter(logger_obj.filters[0])

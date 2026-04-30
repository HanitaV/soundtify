from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from .security import get_appdata_dir


LOG_FILE = "soundtify.log"
_LOGGER: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER:
        return _LOGGER

    logger = logging.getLogger("soundtify")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            filename=f"{get_appdata_dir()}\\{LOG_FILE}",
            maxBytes=512 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    _LOGGER = logger
    return logger


def mask_secret(value: str, keep: int = 4) -> str:
    text = str(value or "")
    if len(text) <= keep * 2:
        return "***" if text else ""
    return f"{text[:keep]}...{text[-keep:]}"


def sanitize_message(message: str) -> str:
    text = str(message)
    patterns = (
        r"(?i)(SAPISID=)([^;\s]+)",
        r"(?i)(__Secure-[13]PAPISID=)([^;\s]+)",
        r"(?i)(SID=)([^;\s]+)",
        r"(?i)(oauth_token=)([^;\s]+)",
        r"(?i)(access_token['\"]?\s*[:=]\s*['\"]?)([^,'\"\s]+)",
        r"(?i)(refresh_token['\"]?\s*[:=]\s*['\"]?)([^,'\"\s]+)",
        r"(?i)(Authorization['\"]?\s*[:=]\s*['\"]?)(Bearer|OAuth)?\s*([^,'\"\s]+)",
    )
    for pattern in patterns:
        text = re.sub(pattern, lambda m: m.group(1) + mask_secret(m.group(m.lastindex)), text)
    return text


def debug(message: str, **context) -> None:
    get_logger().debug(_format(message, context))


def info(message: str, **context) -> None:
    get_logger().info(_format(message, context))


def warning(message: str, **context) -> None:
    get_logger().warning(_format(message, context))


def exception(message: str, **context) -> None:
    get_logger().exception(_format(message, context))


def _format(message: str, context: dict) -> str:
    if context:
        pairs = " ".join(f"{key}={sanitize_message(value)}" for key, value in context.items())
        return sanitize_message(f"{message} {pairs}")
    return sanitize_message(message)

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(log_file: str) -> None:
    """
    Configures the root logger once at startup.
    All modules using logging.getLogger(__name__) will automatically
    bubble up to this root logger.
    """
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    root = logging.getLogger()  # Root logger — no name needed
    root.setLevel(logging.DEBUG)

    # Avoid adding duplicate handlers if called more than once
    if root.handlers:
        return

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(module)-15s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Rolling file — max 5MB, keeps last 3 log files
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Console output (visible when running manually or debugging)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
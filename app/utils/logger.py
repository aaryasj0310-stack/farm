"""Structured logging with contextual job tracking."""
import logging
import sys
from typing import Optional


class JobContextFilter(logging.Filter):
    """Injects job_id into log records."""
    def __init__(self, job_id: Optional[str] = None):
        super().__init__()
        self.job_id = job_id or "SYSTEM"

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "job_id"):
            record.job_id = self.job_id
        return True


class Formatter(logging.Formatter):
    """Clean formatted output with ANSI colors and timestamps."""
    GREY = "\x1b[38;20m"
    BLUE = "\x1b[34;20m"
    CYAN = "\x1b[36;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    FORMAT = "%(asctime)s [%(levelname)s] [JOB:%(job_id)s] [%(name)s] %(message)s"

    FORMATS = {
        logging.DEBUG: GREY + FORMAT + RESET,
        logging.INFO: CYAN + FORMAT + RESET,
        logging.WARNING: YELLOW + FORMAT + RESET,
        logging.ERROR: RED + FORMAT + RESET,
        logging.CRITICAL: BOLD_RED + FORMAT + RESET,
    }

    def format(self, record: logging.LogRecord) -> str:
        log_fmt = self.FORMATS.get(record.levelno, self.FORMAT)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def get_logger(name: str, job_id: Optional[str] = None) -> logging.Logger:
    """Creates or retrieves a logger configured with structured contextual formatting."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if already added
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(Formatter())
        logger.addHandler(handler)
        logger.propagate = False

    logger.addFilter(JobContextFilter(job_id=job_id))
    return logger

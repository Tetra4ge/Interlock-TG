import json
import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured JSON logger.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)

        class JSONFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                log_record = {
                    "level": record.levelname,
                    "name": record.name,
                    "msg": record.getMessage(),
                }
                # Include extra kwargs if any
                if hasattr(record, "extra"):
                    log_record.update(record.extra)
                return json.dumps(log_record)

        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger

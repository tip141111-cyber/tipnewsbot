import logging
import re


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        text = re.sub(r"\d{5,}:[A-Za-z0-9_-]{20,}", "[REDACTED_TOKEN]", text)
        text = re.sub(r"(?i)(authorization[:=]\s*)([^\r\n]+)", r"\1[REDACTED]", text)
        return text


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    for name in ("httpx", "httpcore", "aiogram.event"):
        logging.getLogger(name).setLevel(logging.WARNING)

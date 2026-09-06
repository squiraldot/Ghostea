import logging
from ghostea.services.observability import install_context_logger


def setup_logging() -> logging.Logger:
    install_context_logger()
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )
    return logging.getLogger("Ghostea")

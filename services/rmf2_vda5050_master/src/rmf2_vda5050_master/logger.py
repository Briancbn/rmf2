from __future__ import annotations

import logging

from .websocket import WebsocketConnectionManager, WebsocketLogHandler


def setup_logging(
    ws_manager: WebsocketConnectionManager | None = None,
    *,
    websocket_logging: bool = True,
) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if ws_manager is not None and websocket_logging:
        logging.getLogger().addHandler(WebsocketLogHandler(ws_manager))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

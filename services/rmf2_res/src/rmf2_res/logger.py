from __future__ import annotations

import logging


def setup_logging() -> None:
    # force=True: some third-party deps (e.g. res_plan_execution.plan_executor) call
    # logging.basicConfig(level=DEBUG, ...) as an import side effect, which otherwise
    # wins since basicConfig is a no-op once the root logger already has handlers.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request

from rmf2_task_scheduler.logger import get_logger


def _logger_dep(request: Request) -> logging.Logger:
    module = getattr(request.scope.get("endpoint"), "__module__", __name__)
    return get_logger(module)


LoggerDeps = Annotated[logging.Logger, Depends(_logger_dep)]

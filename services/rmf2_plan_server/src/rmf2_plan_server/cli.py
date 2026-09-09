"""RMF2 RES service — entry point."""

import uvicorn

from .app import app
from .config import settings


def main() -> None:
    config = settings()
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()

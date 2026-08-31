"""VDA5050 master service — FastAPI app with instant action endpoints."""

import uvicorn

from .app import app
from .config import settings


def main() -> None:
    uvicorn.run(app, host=settings().host, port=settings().port)


if __name__ == "__main__":
    main()

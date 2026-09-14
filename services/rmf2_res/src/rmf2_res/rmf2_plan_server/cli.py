"""RMF2 RES service — entry point."""

import uvicorn

from rmf2_res.rmf2_plan_server.app import app
from rmf2_res.rmf2_plan_server.config import settings


def main() -> None:
    config = settings()
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()

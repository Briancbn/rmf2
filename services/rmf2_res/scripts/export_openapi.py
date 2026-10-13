"""Export the OpenAPI schema to a JSON file without starting the server."""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "service",
        choices=["plan_server", "plan_executor"],
        help="Which service's OpenAPI schema to export",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="Directory to write openapi.json into (default: current directory)",
    )
    args = parser.parse_args()

    # Prevent pydantic-settings CliSettingsSource from parsing script args
    sys.argv = sys.argv[:1]

    if args.service == "plan_server":
        from rmf2_res.rmf2_plan_server.app import app
    elif args.service == "plan_executor":
        from rmf2_res.rmf2_plan_executor.app import app

    output = Path(args.output_dir) / "openapi.json"
    output.write_text(json.dumps(app.openapi(), indent=2))
    print(f"OpenAPI schema written to {output}")


if __name__ == "__main__":
    main()

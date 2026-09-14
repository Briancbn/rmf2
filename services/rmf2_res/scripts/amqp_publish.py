"""Manually publish a TaskRequestMsg onto rmf2_plan_server's AMQP topic, for local testing.

Mirrors res_mapf's README `ros2 topic pub` demo, but for this project's AMQP transport.

Usage:
    uv run python scripts/amqp_publish.py --robot-id Manufacturer/1 --goal P_2_2

Environment variables (overridden by CLI flags):
    AMQP_URL        AMQP broker URL          (default: amqp://guest:guest@localhost/)
    AMQP_EXCHANGE   AMQP exchange name       (default: rmf2)
    TOPIC_PREFIX    Plan-server topic prefix (default: rmf2_plan_server/v1)
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid

import pika
from res_plan_server.transport.transport_messages import TaskRequestMsg

from rmf2_res.transport.json_serializer import JsonSerializer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

AMQP_URL = os.environ.get("AMQP_URL", "amqp://guest:guest@localhost/")
AMQP_EXCHANGE = os.environ.get("AMQP_EXCHANGE", "rmf2")
TOPIC_PREFIX = os.environ.get("TOPIC_PREFIX", "rmf2_plan_server/v1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=AMQP_URL, help="AMQP broker URL")
    parser.add_argument("--exchange", default=AMQP_EXCHANGE, help="AMQP exchange name")
    parser.add_argument("--topic-prefix", default=TOPIC_PREFIX, help="Plan-server topic prefix")
    parser.add_argument("--robot-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--task-id", default=None, help="Defaults to a generated task-<random> id")
    args = parser.parse_args()

    task = TaskRequestMsg(
        task_id=args.task_id or f"task-{uuid.uuid4().hex[:8]}",
        robot_id=args.robot_id,
        goal=args.goal,
    )
    body = JsonSerializer().serialize(task)

    topic = f"{args.topic_prefix}/{args.robot_id}/task_request"
    routing_key = topic.replace("/", ".")

    conn = pika.BlockingConnection(pika.URLParameters(args.url))
    try:
        channel = conn.channel()
        channel.basic_publish(
            exchange=args.exchange,
            routing_key=routing_key,
            body=body.encode(),
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=1),
        )
    finally:
        conn.close()

    LOGGER.info("Published to exchange=%s routing_key=%s: %s", args.exchange, routing_key, body)


if __name__ == "__main__":
    main()

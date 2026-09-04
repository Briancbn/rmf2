"""rmf2_vda5050_master_cli — command-line client for the VDA5050 master.

Verbs:
  send_order          Compute shortest path in LIF and send as a VDA5050 Order
  send_instant_action Send an InstantActions message to an AGV
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}:\n{body}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# send_order
# ---------------------------------------------------------------------------


def _build_graph(layout: dict, nx) -> tuple:
    g = nx.DiGraph()
    node_map = {n["nodeId"]: n for n in layout.get("nodes", [])}
    for node_id in node_map:
        g.add_node(node_id)
    for edge in layout.get("edges", []):
        g.add_edge(
            edge["startNodeId"],
            edge["endNodeId"],
            edge_id=edge["edgeId"],
            edge_data=edge,
        )
    return g, node_map


def _build_order(
    manufacturer: str,
    serial_number: str,
    path_nodes: list[str],
    graph,
    node_map: dict,
    map_id: str,
) -> dict:
    vda_nodes = []
    for seq, node_id in enumerate(path_nodes):
        pos = node_map[node_id].get("nodePosition", {})
        vda_nodes.append(
            {
                "nodeId": node_id,
                "sequenceId": seq,
                "released": True,
                "nodePosition": {
                    "x": pos.get("x", 0.0),
                    "y": pos.get("y", 0.0),
                    "mapId": map_id,
                },
                "actions": [],
            }
        )

    vda_edges = []
    for i in range(len(path_nodes) - 1):
        src, dst = path_nodes[i], path_nodes[i + 1]
        edge_data = graph[src][dst]["edge_data"]
        vda_edges.append(
            {
                "edgeId": edge_data["edgeId"],
                "sequenceId": i + 1,
                "startNodeId": src,
                "endNodeId": dst,
                "released": True,
                "actions": [],
            }
        )

    return {
        "headerId": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "manufacturer": manufacturer,
        "serialNumber": serial_number,
        "orderId": str(uuid4()),
        "orderUpdateId": 0,
        "nodes": vda_nodes,
        "edges": vda_edges,
    }


def _amqp_publish_and_wait(
    amqp_url: str,
    exchange: str,
    publish_key: str,
    result_key: str,
    payload: dict,
    timeout: float,
    label: str,
) -> None:
    """Publish ``payload`` to ``publish_key`` and wait up to ``timeout`` seconds for an error on ``result_key``."""
    import time

    try:
        import pika
    except ImportError:
        print("pika is required for AMQP: pip install pika", file=sys.stderr)
        sys.exit(1)

    try:
        conn = pika.BlockingConnection(pika.URLParameters(amqp_url))
    except (pika.exceptions.AMQPConnectionError, OSError) as exc:
        print(f"AMQP connection failed ({amqp_url}): {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        channel = conn.channel()
        channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)

        q = channel.queue_declare(queue="", exclusive=True)
        channel.queue_bind(
            exchange=exchange, queue=q.method.queue, routing_key=result_key
        )

        channel.basic_publish(
            exchange=exchange,
            routing_key=publish_key,
            body=json.dumps(payload).encode(),
            properties=pika.BasicProperties(content_type="application/json"),
        )
        print(f"{label} sent via AMQP to {publish_key}")

        received: list[dict] = []

        def _on_message(ch, method, _props, body: bytes) -> None:
            received.append(json.loads(body))
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(
            queue=q.method.queue, on_message_callback=_on_message, auto_ack=False
        )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not received:
            conn.process_data_events(time_limit=0.1)
    except pika.exceptions.AMQPError as exc:
        print(f"AMQP error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

    if not received:
        print("No result received within timeout — order may still be processing")
        return
    result = received[0]
    print(f"Result: {json.dumps(result, indent=2)}")
    if result.get("errors"):
        sys.exit(1)


def _send_order_amqp(args: argparse.Namespace, order: dict) -> None:
    prefix = args.amqp_topic_prefix.replace("/", ".")
    _amqp_publish_and_wait(
        amqp_url=args.amqp_url,
        exchange=args.amqp_exchange,
        publish_key=f"{prefix}.assign_order",
        result_key=f"{prefix}.assign_order_result",
        payload=order,
        timeout=args.amqp_timeout,
        label=f"Order {order['orderId']}",
    )


def _send_instant_action_amqp(args: argparse.Namespace, payload: dict) -> None:
    prefix = args.amqp_topic_prefix.replace("/", ".")
    _amqp_publish_and_wait(
        amqp_url=args.amqp_url,
        exchange=args.amqp_exchange,
        publish_key=f"{prefix}.assign_instant_actions",
        result_key=f"{prefix}.assign_instant_actions_result",
        payload=payload,
        timeout=args.amqp_timeout,
        label=f"InstantActions '{args.action_type}'",
    )


def cmd_send_order(args: argparse.Namespace) -> None:
    try:
        import networkx as nx
    except ImportError:
        print(
            "networkx is required for send_order: "
            "pip install 'rmf2-vda5050-master[cli_client]'",
            file=sys.stderr,
        )
        sys.exit(1)

    base = args.server.rstrip("/")

    print(f"Fetching LIF from {base}/layout/download ...")
    lif = _fetch_json(f"{base}/layout/download")

    layouts = lif.get("layouts", [])
    if not layouts:
        print("No layouts found in LIF.", file=sys.stderr)
        sys.exit(1)

    if args.layout_id:
        layout = next((l for l in layouts if l.get("layoutId") == args.layout_id), None)
        if layout is None:
            available = [l.get("layoutId") for l in layouts]
            print(
                f"Layout '{args.layout_id}' not found. Available: {available}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        layout = layouts[0]
        print(f"Using layout: {layout.get('layoutId')}")

    map_id = layout.get("layoutId", "")
    graph, node_map = _build_graph(layout, nx)
    available_nodes = sorted(node_map)

    missing = [n for n in (args.start, args.end) if n not in node_map]
    if missing:
        print(f"Node(s) not found: {missing}", file=sys.stderr)
        print(f"Available waypoints: {available_nodes}", file=sys.stderr)
        sys.exit(1)

    try:
        path = nx.shortest_path(graph, args.start, args.end)
    except nx.NetworkXNoPath:
        print(f"No path from '{args.start}' to '{args.end}'.", file=sys.stderr)
        sys.exit(1)

    print(f"Shortest path ({len(path)} nodes): {' -> '.join(path)}")

    order = _build_order(
        args.manufacturer, args.serial_number, path, graph, node_map, map_id
    )

    if args.transport == "amqp":
        _send_order_amqp(args, order)
        return

    url = f"{base}/orders/{args.manufacturer}/{args.serial_number}/assign"
    print(f"Sending order {order['orderId']} ...")
    result = _post_json(url, order)
    print(f"Result: {json.dumps(result, indent=2)}")


# ---------------------------------------------------------------------------
# send_instant_action
# ---------------------------------------------------------------------------


def cmd_send_instant_action(args: argparse.Namespace) -> None:
    action: dict = {
        "actionType": args.action_type,
        "actionId": args.action_id or str(uuid4()),
        "blockingType": args.blocking_type,
    }
    if args.param:
        action["actionParameters"] = [
            {"key": k, "value": v} for k, _, v in (p.partition("=") for p in args.param)
        ]

    payload = {
        "headerId": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "manufacturer": args.manufacturer,
        "serialNumber": args.serial_number,
        "actions": [action],
    }

    if args.transport == "amqp":
        _send_instant_action_amqp(args, payload)
        return

    base = args.server.rstrip("/")
    url = f"{base}/instant_actions/{args.manufacturer}/{args.serial_number}/assign"
    print(
        f"Sending instant action '{args.action_type}' to {args.manufacturer}/{args.serial_number} ..."
    )
    result = _post_json(url, payload)
    print(f"Result: {json.dumps(result, indent=2)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rmf2_vda5050_master_cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--server",
        default="http://localhost:8000/v1",
        help="Master server base URL (default: http://localhost:8000/v1)",
    )
    parser.add_argument("--manufacturer", required=True)
    parser.add_argument("--serial-number", required=True)
    parser.add_argument(
        "--transport",
        choices=["http", "amqp"],
        default="http",
        help="Transport to use (default: http)",
    )
    parser.add_argument(
        "--amqp-url",
        default="amqp://localhost",
        metavar="URL",
        help="AMQP broker URL (default: amqp://localhost)",
    )
    parser.add_argument(
        "--amqp-exchange",
        default="rmf2",
        help="AMQP exchange name (default: rmf2)",
    )
    parser.add_argument(
        "--amqp-topic-prefix",
        default="rmf2_vda5050_master/v1",
        help="Topic prefix (default: rmf2_vda5050_master/v1)",
    )
    parser.add_argument(
        "--amqp-timeout",
        type=float,
        default=3.0,
        metavar="SECONDS",
        help="Seconds to wait for an error response (default: 3.0)",
    )

    sub = parser.add_subparsers(dest="verb", required=True)

    # --- send_order ---
    p_order = sub.add_parser("send_order", help="Send a shortest-path order to an AGV")
    p_order.add_argument("--start", required=True, metavar="NODE_ID")
    p_order.add_argument("--end", required=True, metavar="NODE_ID")
    p_order.add_argument(
        "--layout-id",
        default=None,
        help="Layout ID to route within (default: first layout)",
    )

    # --- send_instant_action ---
    p_ia = sub.add_parser(
        "send_instant_action", help="Send an InstantActions message to an AGV"
    )
    p_ia.add_argument(
        "--action-type",
        required=True,
        help="VDA5050 action type (e.g. startPause, stopPause)",
    )
    p_ia.add_argument(
        "--action-id", default=None, help="Action ID (auto-generated if omitted)"
    )
    p_ia.add_argument(
        "--blocking-type", default="NONE", choices=["NONE", "SOFT", "HARD"]
    )
    p_ia.add_argument(
        "--param",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help="Action parameter (repeatable, e.g. --param duration=5.0)",
    )

    args = parser.parse_args()
    if args.verb == "send_order":
        cmd_send_order(args)
    elif args.verb == "send_instant_action":
        cmd_send_instant_action(args)


if __name__ == "__main__":
    main()

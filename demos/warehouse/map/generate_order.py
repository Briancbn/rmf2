import json
import networkx as nix
from uuid import uuid4

from argparse import ArgumentParser

parser = ArgumentParser()

parser.add_argument("-s", "--start", type=str, required=True)
parser.add_argument("-e", "--end", type=str, required=True)
parser.add_argument("-m", "--manufacturer", type=str, default="Manufacturer")
parser.add_argument("--serial", type=str, required=True)

args = parser.parse_args()
start_wp = args.start
end_wp = args.end
manufacturer = args.manufacturer
serial = args.serial

with open("./warehouse.lif.json", "r") as f:
    map_raw = json.load(f)

graph = nx.Graph()
for node in map_raw["nodes"]:
    graph.add_node(node["node_id"], metadata=node)

for edge in map_raw["edges"]:
    graph.add_edge(edge["start_node_id"], edge["end_node_id"], metadata=edge)

path = nx.shortest_path(graph, source=start_wp, target=end_wp, weight="weight")

node_metadata = nx.get_node_attributes(graph, "metadata")

order = {
    "manufacturer": manufacturer,
    "serial_number": serial,
    "order": {
        "header": {
            "header_id": 0,
            "timestamp": 0,
            "version": "2.0.0",
            "manufacturer": manufacturer,
            "serial_number": serial,
        },
        "order_id": str(uuid4()),
        "order_update_id": 0,
        "zone_set_id": [],
        "nodes": [],
        "edges": [],
    },
}

if not path:
    print(path)
    print("No Path Found!")

for idx, node_id in enumerate(path[:-1]):
    node_data = node_metadata[node_id]
    node = {
        ""
    }
    print(graph.edges[node_id, path[idx + 1]]["metadata"])
    order["order"]["nodes"].append

print(node_metadata[path[-1]])

import json
import networkx as nx
from uuid import uuid4
import yaml

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

with open("../map/warehouse.lif.json", "r") as f:
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

def add_node_to_order(node_data, sequence_id):
    node = {
        "node_id": node_data["node_id"],
        "sequence_id": sequence_id,
        "released": True,
        "actions": [],
        "node_position": [{
            "x": node_data["x"],
            "y": node_data["y"],
            "theta": [node_data["theta"]],
            "allowed_deviation_x_y": [node_data["allowed_deviation_xy"]],
            "map_id": map_raw["map_info"]["map_id"],
            "map_description": [],
        }],
    }
    order["order"]["nodes"].append(node)

def add_edge_to_order(edge_data, sequence_id, start_node, end_node):
    edge = {
        "edge_id": edge_data["edge_id"],
        "sequence_id": sequence_id,
        "released": True,
        "start_node_id": start_node,
        "end_node_id": end_node,
        "actions": [],
        "edge_description": [],
        "max_speed": [edge_data["max_speed"]],
        "length": [edge_data["length"]],
        "max_height": [], "min_height": [],
        "orientation": [], "orientation_type": [],
        "direction": [], "rotation_allowed": [], "max_rotation_speed": [],
        "trajectory": []
    }
    order["order"]["edges"].append(edge)


for idx, node_id in enumerate(path[:-1]):
    node_data = node_metadata[node_id]
    edge_data = graph.edges[node_id, path[idx + 1]]["metadata"]

    add_node_to_order(node_data, idx * 2)
    add_edge_to_order(edge_data, idx * 2 + 1, node_id, path[idx + 1])

add_node_to_order(node_metadata[path[-1]], (len(path) - 1) * 2)

with open(f"../agv/sample_order_{start_wp}_{end_wp}_{manufacturer}_{serial}.yaml", "w") as f:
    yaml.dump(order, f)

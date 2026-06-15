import json
from typing import TypedDict, Dict, Sequence, Any, Tuple

import yaml

IN_FILE = 'warehouse_os_setup.yaml'
OUT_FILE = 'warehouse_oss.lif.json'

class _MAPInfo(TypedDict):
    map_id: str
    map_version: str
    map_status: str
    map_descriptor: str

class _Node(TypedDict):
    node_id: str
    x: float
    y: float
    theta: float
    allowed_deviation_xy: float
    allowed_deviation_theta: float
    map_description: str

class _Edge(TypedDict):
    edge_id: str
    start_node_id: str
    end_node_id: str
    bidirectional: bool
    max_speed: float
    length: float

class _Layout(TypedDict):
    map_info: _MAPInfo
    nodes: Sequence[_Node]
    edges: Sequence[_Edge]

class _Building(TypedDict):
    name: str
    rows: int
    columns: int
    coordinate_system: str
    levels: Dict[str, _Level]

class _Level(TypedDict):
    lanes: Sequence[_Lane]
    vertices: Sequence[_Vertice]

_Vertice = Tuple[float, float, float, str, Any]

class _LaneInfo(TypedDict):
    bidirectional: Tuple[int, bool]

_Lane = Tuple[int, int, _LaneInfo]

def main():
    with open(IN_FILE, 'r') as f_in:
        in_data: _Building = yaml.safe_load(f_in)

    levels = in_data["levels"]

    for level_name, level_data in levels.items():
        layout_name = level_name
        print(f"Exporting Level [{level_name}] ({level_name}.lif.json)")

        # Fill Map Info
        map_info: _MAPInfo = {
            "map_id": level_name,
            "map_version": "1.0",
            "map_status": "ENABLED",
            "map_descriptor": "RMF2 Open Source Warehouse Demo",
        }
        print("Successfully retrieved Map Info:")
        print(json.dumps(map_info, indent=2))

        # Fill nodes
        nodes: Sequence[_Node] = []
        for vertice in level_data["vertices"]:
            node = {
                "node_id": vertice[3],
                "x": vertice[0],
                "y": vertice[1],
                "theta": 0.0,
                "allowed_devation_xy": 0.5,
                "allowed_devation_theta": 0.1,
                "map_description": "",
            }
            nodes.append(node)

        edges: Sequence[_Edge] = []
        for idx, lane in enumerate(level_data["lanes"]):
            start_node = nodes[lane[0]]
            end_node = nodes[lane[1]]
            edge = {
                "edge_id": f"E{idx + 1}",
                "start_node_id": start_node["node_id"],
                "end_node_id": end_node["node_id"],
                "bidirectional": lane[2]["bidirectional"][1],
                "max_speed": 1.0,
                "length": 1.0,  #TODO
            }
            edges.append(edge)

        # Consolidate the data into Layout
        out_data: _Layout = {
            "map_info": map_info,
            "nodes": nodes,
            "edges": edges,
        }

        print("Total nodes: %d" % len(nodes))
        print("Total edges: %d" % len(edges))

        out_file = f"{layout_name}.lif.json"
        with open(out_file, "w") as f_out:
            json.dump(out_data, f_out, indent=2)

        print(f"Successfully converted [{layout_name}] to [{out_file}]")

    print("Done")

if __name__ == "__main__":
    main()

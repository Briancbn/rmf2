import json
from PIL import Image

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

IN_FILE = 'warehouse.lif.json'

def main():
    with open(IN_FILE, 'r') as f_in:
        in_data = json.load(f_in)

    graph = nx.Graph()
    pos = {}
    for node in in_data["nodes"]:
        node_id = node["node_id"]
        graph.add_node(node_id)
        pos[node_id] = (node["x"], node["y"])

    for edge in in_data["edges"]:
        graph.add_edge(edge["start_node_id"], edge["end_node_id"])

    plt.figure(dpi=500)
    nx.draw(graph, node_size=3, width=0.5, pos=pos)
    pos_labels = {node: (coords[0], coords[1] + 0.3) for node, coords in pos.items()}
    nx.draw_networkx_labels(graph, pos=pos_labels, font_size=2, horizontalalignment='left')

    out_file = f'{in_data["map_info"]["map_id"]}.png'
    plt.savefig(out_file)
    image = Image.open(out_file)
    image.show()

if __name__ == "__main__":
    main()

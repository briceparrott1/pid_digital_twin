import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import app_path, get_settings

LEVEL_COLORS = {
    "equipment": "#4C72B0",
    "instrument": "#55A868",
    "valve": "#C44E52",
    "junction": "#8C8C8C",
    "out_of_system": "#DD8452",
}
DEFAULT_COLOR = "#CCCCCC"


def find_run_dir(run_number: int) -> Path:
    settings = get_settings()
    results_root = app_path(settings.results_dir)
    matches = sorted(results_root.glob(f"run_{run_number}_*"))
    if not matches:
        raise FileNotFoundError(
            f"No results directory found for run {run_number} in {results_root}"
        )
    return matches[0]


def build_graph(extraction: dict) -> nx.Graph:
    graph = nx.Graph()
    for node in extraction["nodes"]:
        graph.add_node(node["component_name"], level=node.get("level"))
    for conn in extraction["connections"]:
        graph.add_edge(
            conn["start_id"], conn["end_id"], line_type=conn.get("line_type")
        )
    return graph


def draw_graph(graph: nx.Graph, title: str, output_path: Path, show: bool = True) -> None:
    colors = [
        LEVEL_COLORS.get(data.get("level"), DEFAULT_COLOR)
        for _, data in graph.nodes(data=True)
    ]

    plt.figure(figsize=(16, 12))
    pos = nx.spring_layout(graph, seed=42, k=0.6)
    nx.draw(
        graph,
        pos,
        with_labels=True,
        node_color=colors,
        node_size=600,
        font_size=7,
        edge_color="#999999",
    )
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"Saved graph image to {output_path}")
    if show:
        plt.show()
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize a run's extracted P&ID graph")
    parser.add_argument(
        "--run",
        type=int,
        required=True,
        help="Run number (the n in results/run_n_<description>)",
    )
    args = parser.parse_args()

    run_dir = find_run_dir(args.run)
    extraction = json.loads((run_dir / "extraction.json").read_text())

    graph = build_graph(extraction)
    draw_graph(graph, title=run_dir.name, output_path=run_dir / "graph.png")


if __name__ == "__main__":
    main()

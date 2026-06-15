import argparse
import asyncio
import json
from datetime import datetime, timezone

from core.config import app_path, get_settings
from tools.extract import extract_page
from tools.line_colorizer import colorize_lines
from tools.preprocess import preprocess
from tools.prompts import CONNECTION_PROMPT, EQUIPMENT_METADATA_PROMPT, NODE_ONLY_PROMPT
from tools.render import render_page
from tools.resolve import flatten_metadata, resolve
from tools.segment import segment


def _merge_node(existing: dict, new: dict) -> None:
    """Equipment nodes are referenced twice on the diagram — once near their
    symbol, once with their spec callout — so a later sighting may carry
    metadata fields the first sighting didn't see. Fill in only the missing
    ones."""
    for key, value in new.items():
        if key.startswith("metadata_") and key not in existing:
            existing[key] = value


async def run_algo(description: str = "run", debug: bool = False) -> dict:
    """Render page 1 of the P&ID, then run a three-pass extraction: pass 1
    extracts nodes from uncolored segments, pass 2 extracts connections from
    the full color-coded image given the pass-1 node list, and pass 3 fills
    in equipment metadata from the full enhanced image."""
    settings = get_settings()
    image = render_page(str(app_path(settings.diagram_path)), page_index=0)
    enhanced, clean = preprocess(image)

    # PASS 1 — nodes from UNCOLORED segments
    regions = segment(enhanced, clean, k=5)
    all_nodes: dict[str, dict] = {}
    pass1_results = []
    for region in regions:
        r = resolve(await extract_page(region, NODE_ONLY_PROMPT, settings.model))
        for node in r.get("nodes", []):
            name = node["component_name"]
            if name in all_nodes:
                _merge_node(all_nodes[name], node)
            else:
                all_nodes[name] = node
        pass1_results.append(r)

    # PASS 2 — connections from FULL COLOR-CODED image + known node list
    color_coded, line_registry = colorize_lines(enhanced, clean)
    node_list = json.dumps(sorted(all_nodes.keys()), indent=2)
    conn_result = resolve(
        await extract_page(
            color_coded,
            CONNECTION_PROMPT.format(node_list=node_list),
            settings.model,
        )
    )

    for j in conn_result.get("junctions", []):
        j.setdefault("level", "junction")
        name = j["component_name"]
        if name in all_nodes:
            _merge_node(all_nodes[name], j)
        else:
            all_nodes[name] = j

    # PASS 3 — equipment metadata from the FULL ENHANCED image
    equipment_names = [
        n["component_name"] for n in all_nodes.values() if n.get("level") == "equipment"
    ]
    meta_result: dict = {"equipment": {}}
    equipment_specs_found = 0
    if equipment_names:
        eq_list = json.dumps(sorted(equipment_names), indent=2)
        try:
            meta_result = resolve(
                await extract_page(
                    enhanced,
                    EQUIPMENT_METADATA_PROMPT.format(equipment_list=eq_list),
                    settings.model,
                )
            )
        except Exception as e:
            print(f"Equipment metadata pass failed, skipping: {e}")

        empty_specs = []
        for name, specs in (meta_result.get("equipment") or {}).items():
            if name not in all_nodes:
                continue
            if specs:
                _merge_node(all_nodes[name], flatten_metadata(specs))
                equipment_specs_found += 1
            else:
                empty_specs.append(name)
        if empty_specs:
            print(f"Equipment with no metadata found: {', '.join(sorted(empty_specs))}")

    resolved = {
        "nodes": list(all_nodes.values()),
        "connections": conn_result.get("connections", []),
    }

    if debug:
        debug_dir = app_path(settings.results_dir) / description
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "color_coded.png").write_bytes(color_coded)
        for i, region in enumerate(regions):
            (debug_dir / f"segment_{i}.png").write_bytes(region)
        (debug_dir / "pass1_results.json").write_text(
            json.dumps(pass1_results, indent=2)
        )
        (debug_dir / "pass2_result.json").write_text(json.dumps(conn_result, indent=2))
        (debug_dir / "pass3_result.json").write_text(json.dumps(meta_result, indent=2))

    return {
        "raw": {"pass1": pass1_results, "pass2": conn_result, "metadata": meta_result},
        "resolved": resolved,
        "colorized_image": color_coded,
        "segments": regions,
        "meta": {
            "description": description,
            "page": 1,
            "model": settings.model,
            "segments": len(regions),
            "total_nodes": len(all_nodes),
            "total_connections": len(resolved["connections"]),
            "junctions_created": len(conn_result.get("junctions", [])),
            "lines_detected": len(line_registry),
            "equipment_metadata_call": bool(equipment_names),
            "equipment_specs_found": equipment_specs_found,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the P&ID extraction algorithm")
    parser.add_argument(
        "--description", default="run", help="Short tag describing this run"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Write per-segment debug artifacts to results/{description}/",
    )
    args = parser.parse_args()

    result = asyncio.run(run_algo(args.description, debug=args.debug))
    print(json.dumps(result["resolved"], indent=2))


if __name__ == "__main__":
    main()

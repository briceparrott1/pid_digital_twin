import uuid


def _build_color_adjacency(line_registry: list[dict], tol: float = 60.0) -> dict:
    """
    Two colors are adjacent if any of their endpoints are within tol pixels.
    Returns {color_name: set(adjacent_color_names)}.
    """
    def endpoints(line):
        return [(line["x1"], line["y1"]), (line["x2"], line["y2"])]

    adj = {l["color_name"]: set() for l in line_registry}
    for i, a in enumerate(line_registry):
        a_pts = endpoints(a)
        for b in line_registry[i + 1:]:
            b_pts = endpoints(b)
            near = any(
                abs(ax - bx) <= tol and abs(ay - by) <= tol
                for ax, ay in a_pts for bx, by in b_pts
            )
            if near:
                adj[a["color_name"]].add(b["color_name"])
                adj[b["color_name"]].add(a["color_name"])
    return adj


def stitch_by_color(
    segment_results: list[dict],
    line_registry: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Reconstruct connections by walking chains of color-adjacent line segments
    between components.

    A pipe is split into many colored segments. The VLM reports which
    components each color touches. Colors that meet in space (per the line
    registry geometry) belong to the same physical pipe. We walk the color
    adjacency graph from each component until we reach other components,
    producing connections.

    Returns (connections, junction_nodes) in the V2 contract.
    """
    # color -> set of components the VLM saw it touch (across all segments)
    color_components: dict[str, set] = {}
    color_linetype: dict[str, str] = {}
    for r in segment_results:
        for c in r.get("connections", []):
            col = c.get("color")
            if not col or col == "unreadable":
                continue
            color_components.setdefault(col, set()).update(c.get("endpoints", []))
            if c.get("line_type"):
                color_linetype.setdefault(col, c["line_type"])

    adjacency = _build_color_adjacency(line_registry)

    # ensure every color seen by the VLM exists in adjacency (even if registry missed it)
    for col in color_components:
        adjacency.setdefault(col, set())

    # walk color chains to find component-to-component paths.
    # for each colored segment that touches >=1 component, BFS across adjacent
    # colors collecting every component reachable through the color chain.
    # group of colors forming one connected pipe -> the components they touch.
    visited_colors = set()
    pipe_groups = []  # each is (set_of_colors, set_of_components)

    all_colors = set(adjacency.keys()) | set(color_components.keys())
    for start_color in all_colors:
        if start_color in visited_colors:
            continue
        # BFS over adjacency from this color
        group_colors = set()
        group_components = set()
        queue = [start_color]
        while queue:
            col = queue.pop()
            if col in visited_colors:
                continue
            visited_colors.add(col)
            group_colors.add(col)
            group_components.update(color_components.get(col, set()))
            for nxt in adjacency.get(col, set()):
                if nxt not in visited_colors:
                    queue.append(nxt)
        if group_components:
            pipe_groups.append((group_colors, group_components))

    # build connections from each pipe group
    connections = []
    junctions = []
    for colors, components in pipe_groups:
        comps = sorted(components)
        lt = next((color_linetype[c] for c in colors if c in color_linetype), "major_process")
        pipeline = str(uuid.uuid4())
        rep_color = sorted(colors)[0]

        if len(comps) < 2:
            continue  # dangling pipe, only reaches one component
        elif len(comps) == 2:
            connections.append({
                "line_type": lt,
                "start_id": comps[0],
                "end_id": comps[1],
                "pipeline": pipeline,
                "metadata": {"colors": sorted(colors)},
                "confidence": "medium",
            })
        else:
            # pipe reaches 3+ components -> junction hub
            jid = f"j_{rep_color}"
            junctions.append({
                "level": "junction",
                "component_name": jid,
                "metadata": {"colors": sorted(colors)},
                "confidence": "medium",
            })
            for ep in comps:
                connections.append({
                    "line_type": lt,
                    "start_id": jid,
                    "end_id": ep,
                    "pipeline": pipeline,
                    "metadata": {"colors": sorted(colors)},
                    "confidence": "medium",
                })

    return connections, junctions
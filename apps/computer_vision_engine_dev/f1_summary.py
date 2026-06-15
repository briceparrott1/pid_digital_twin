import json
import re
from pathlib import Path

from core.config import app_path, get_settings


def _run_number(run_dir: Path) -> int:
    return int(re.match(r"run_(\d+)_", run_dir.name).group(1))


def main() -> None:
    results_root = app_path(get_settings().results_dir)
    header = "| Run | Node F1 | Connection F1 | Fuzzy F1 |"
    divider = "|---|---|---|---|"
    rows = []

    for run_dir in sorted(results_root.glob("run_*"), key=_run_number):
        metrics_path = run_dir / "metrics.json"
        if not metrics_path.exists():
            rows.append(f"| {run_dir.name} | - | - | - |")
            continue

        metrics = json.loads(metrics_path.read_text())
        node_f1 = metrics["node_detection"]["overall"]["f1"]
        topology_f1 = metrics["connections"].get("topology", {}).get("f1")
        fuzzy_f1 = metrics["connections"]["fuzzy"]["f1"]
        topology_str = f"{topology_f1:.2f}" if topology_f1 is not None else "-"
        rows.append(
            f"| {run_dir.name} | {node_f1:.2f} | {topology_str} | {fuzzy_f1:.2f} |"
        )

    out_path = results_root / "f1_summary.md"
    out_path.write_text("\n".join(["# F1 Summary", "", header, divider, *rows]) + "\n")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

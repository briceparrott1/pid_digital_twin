# Architecture

Per-app internals and reference material for the interface-take-home-monorepo. Read the relevant section when working inside a given app; the top-level orientation lives in `CLAUDE.md`.

## App-by-app orientation

### `apps/computer_vision/` — Production FastAPI service

Entry point: `main.py`. Core flow:

1. `POST /start-job` → creates a Neo4j `Job` node, schedules `pipeline.py::run_pipeline` as a background task
2. `run_pipeline` runs two branches in parallel via `asyncio.gather`:
   - `services/extractions.py::build_pid_graph` — renders PDF, runs the recursive-bisection extraction engine (`engine/orchestrator.py`), writes nodes/edges to Neo4j
   - `services/extractions.py::build_sop_requirements` — parses `.docx` SOP to structured rules via Claude
3. LangGraph agent (`agent/graph.py`) walks each SOP rule, queries Neo4j, writes `sop_violation` flags back to component nodes
4. `GET /graph/{job_id}` and `GET /report/{job_id}` serve results

Key directories:
- `engine/` — recursive-bisection extraction engine (deterministic ink-cost cuts, concurrent VLM leaf reads, seam-merge; orchestrated via `engine/orchestrator.py`)
- `agent/` — LangGraph SOP-violation agent; two rule types: `component_specifications` (VLM-assisted) and `incompatible_components` (pure Cypher)
- `db/` — `neo4j_client.py`, `loader.py` (writes), `queries.py` (reads)
- `data/sop/` — SOP `.docx` test cases; `sop_truth/` holds expected violations per case

### `apps/frontend/` — React/Vite/TS dashboard

`src/` contains React components. Proxies `/api/*` to the FastAPI service. Uses `react-cytoscapejs` to render the extracted graph; `Report.tsx` shows the violation list.

## Neo4j graph model

```
(:Job {id, status, created_at})
   │ :CONTAINS
   ▼
(component {component_name, level, metadata_*, confidence, sop_violation, violation})
   │ :CONNECTED_TO {job_id, line_type, pipeline}
   ▼
(component)
```

`level` values: `equipment`, `instrument`, `valve`, `junction`, `out_of_system`.

## Known gaps / next steps

Note: the truth-set annotation errors gap is surfaced in `CLAUDE.md` so it's always in context. The full list:

- Truth set has annotation errors; audit before drawing strong conclusions from F1 numbers.
- Equipment metadata extraction is unreliable (pass 3 sees the full page instead of a focused segment).
- Multi-page benchmarks don't exist — all eval is page 1 only.
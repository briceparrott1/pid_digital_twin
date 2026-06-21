# P&ID to Digital Twin & SOP Cross-Referencing

A tool that automates cross-referencing P&ID diagrams against SOP documents, a painstaking process when done by hand. It solves two problems. First, it builds a graph-based digital twin of a P&ID in Neo4j. Second, it cross-references each SOP requirement against that twin using a mix of agentic and deterministic checks, flagging violations on the graph.

# tldr

I used a VLM-based approach instead of a learning approach because I found a paper showing a training-free VLM pipeline outperforming an industry-trained model, and I couldn't find a usable pretrained detector anyway. With a custom recursive bisection segmentation and post-processing merge technique, I achieved a node detection F1 of 0.97 and connection F1 of 0.87 on a manually created truth set of the first page of the given P&ID, after manually marking junctions and coloring the process lines on the diagram (I abstracted this away from the paper's approach because I have no experience with image processing). I also found that giving a Claude chat instance the same image and prompt achieves better accuracy than my segmentation approach, it segments itself using tools. However, when I tried to replicate this via API, I accidentally ran up a $60 token balance in under six minutes by enabling tools and extended thinking with no cost ceiling. This suggests that deterministic segmentation still has real merit. SOP cross-referencing is nearly 100% accurate for flagging inconsistent component specs and incompatible parts, and is overall bottlenecked by graph accuracy. Next steps would be putting this in a process engineer's hands, validating truth sets, exploring a single streaming VLM call with thinking and tooling enabled within a cost cap, and learning more about computer vision and image processing.

I have a newfound appreciation for what you all are doing, even making that one truth set was painful.

**below, the quick start says you can choose from 4 test cases; however, because I only took the time to manually color page 1 of the diagram, some of the test cases become irrelevant as they deal with components on page 2 and page 3. The SOP cross referencer agent is bottlenecked by the graph anyway (ie, if the data is good, the agent will work), and if you checkout the main branch, all test cases an be ran there since it runs the v1 engine, which doesn't rely on pre colored pages. 


## Quick start

```bash
# from the repo root
cp .env.example .env          # add ANTHROPIC_API_KEY, NEO4J_PASSWORD
docker compose up             # starts neo4j, computer-vision (API), frontend
```

- Frontend: http://localhost:5173
- API: http://localhost:8000 (`/health` to verify)
- Neo4j browser: http://localhost:7474

Click start job in the frontend and choose a test case. It kicks off the pipeline, polls for completion, then renders the extracted graph and the SOP violation report.

Each selectable test case corresponds to one of the SOP documents in `computer_vision/data/sop/`. The expected violations for each case, meaning the ground truth of what the agent should flag, live in `/apps/computer_vision/data/sop/sop_truth/`. You can compare the generated report against the expected result for the case you ran.

The longest run I experienced was 4.5 minutes and $1.30 in tokens. This seemed to be an outlier, but given the long and costly nature of runs, I did not conduct significant testing of the entire pipeline. You may want to start a job and come back to this file while it runs.

See [`findings.md`](findings.md) for detailed eval metrics, [`thoughts.md`](thoughts.md) for approach decisions and reflections, and [`architecture.md`](architecture.md) for per-module internals.

## Architecture

A monorepo with two apps: a FastAPI backend (`computer_vision`) and a React/Vite/TS dashboard (`frontend`), wired together with Docker Compose and a shared `.env`.

```
interface-take-home-monorepo/
├── .env                    # ANTHROPIC_API_KEY, NEO4J_USER, NEO4J_PASSWORD
├── docker-compose.yaml     # neo4j + computer-vision + frontend
├── docs/                   # readme, architecture, findings, thoughts
└── apps/
    ├── computer_vision/    # production FastAPI service (port 8000)
    └── frontend/           # React/Vite/TS dashboard (port 5173)
```

Docker Compose wires three services:

| Service | Build | Port | Notes |
|---|---|---|---|
| `neo4j` | `neo4j:5.18` | 7474 / 7687 | auth from `NEO4J_USER` / `NEO4J_PASSWORD` |
| `computer-vision` | `./apps/computer_vision` | 8000 | FastAPI; waits for healthy `neo4j` |
| `frontend` | `./apps/frontend` | 5173 | Vite dev server; proxies `/api` → API |

### Request lifecycle

```
frontend  ──POST /start-job──▶  computer-vision (FastAPI)
        ◀─GET /graph,/report──
                                       │
                       background: run_pipeline(job_id)
                                       │
        ┌──────────────────────────────────────────────┐
        │  in parallel (asyncio.gather):                 │
        │  1. build_pid_graph     2. build_sop_requirements
        │     render PDF             parse sop.docx       │
        │     recursive-bisection    Claude → rules        │
        │     engine → Neo4j                              │
        └──────────────────────────────────────────────┘
                                       │
                  3. run_agent(job_id, requirements)
                     LangGraph walks each SOP rule, queries
                     the graph, writes sop_violation flags back
                                       │
                                   ┌────────┐
                                   │ Neo4j  │
                                   └────────┘
```

1. The frontend posts to `/api/start-job`. `main.py` creates a `Job` node and schedules `run_pipeline(job_id)` as a background task, returning `job_id` immediately.
2. `run_pipeline` runs two builds in parallel:
   - `build_pid_graph` renders the P&ID PDF, runs the recursive-bisection extraction engine, and writes nodes/edges to Neo4j under this job.
   - `build_sop_requirements` parses `sop.docx` to text and sends it to Claude (`SOP_EXTRACTION_PROMPT`) to get a list of structured rules.
3. The LangGraph agent checks each SOP requirement against the graph and writes violations back onto offending nodes.
4. Job status becomes `complete`. The frontend polls `/api/report/{job_id}`, then fetches `/api/graph/{job_id}` and renders it with Cytoscape.

### API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | `{status, neo4j_connected, sop_loaded}` |
| `/start-job` | POST | Creates a `Job`, schedules the pipeline, returns `job_id` |
| `/graph/{job_id}` | GET | Job's nodes/edges as Cytoscape elements + summary counts |
| `/report/{job_id}` | GET | Job status + recorded SOP violations |

### Backend layout

```
computer_vision/
├── main.py              # FastAPI routes
├── pipeline.py          # run_pipeline orchestration + post-run eval
├── core/
│   ├── config.py        # settings (paths, model IDs, neo4j URI)
│   └── logging_config.py
├── parsers/
│   ├── pid_parser.py    # PDF → PNG pages via PyMuPDF
│   └── sop_parser.py    # .docx → plain text
├── extraction/
│   ├── extractors.py    # build_sop_requirements: Claude call + parsing
│   └── prompts.py       # SOP_EXTRACTION_PROMPT
├── engine/              # recursive-bisection P&ID extraction engine
│   ├── orchestrator.py  # entry point: run_algo(colored, uncolored)
│   ├── config.py        # typed frozen dataclasses (Stop/Cut/Render/Vlm)
│   ├── types.py         # all data contracts (Segment, Node, Edge, …)
│   ├── graph.py         # collapses root Subgraph → PageGraph
│   ├── evaluate.py      # scores a run against data/truth_set.json
│   ├── cut/             # cost_map, best_cut, split
│   ├── preprocess/      # render PDF → NumPy arrays (colored + uncolored)
│   ├── recurse/         # stop conditions, recursive process
│   ├── leaf/            # VLM boundary: prompt, api client, response parser
│   ├── merge/           # seam resolution: lines, nodes, dedupe, orchestration
│   └── instrument/      # run counters / telemetry
├── services/
│   └── extractions.py   # build_pid_graph(), build_sop_requirements()
├── agent/
│   ├── graph.py         # LangGraph StateGraph for SOP violation checking
│   ├── state.py         # AgentState
│   └── tools.py         # query_components, query_connections, write_violation
├── db/
│   ├── neo4j_client.py  # driver singleton
│   ├── loader.py        # write_job, write_extraction, update_job_status
│   └── queries.py       # read-side Cypher queries
├── models/
│   ├── job.py           # Job pydantic model
│   ├── graph.py         # graph response schema
│   └── report.py        # report response schema
├── data/
│   ├── pid/             # colored.pdf, uncolored.pdf (mounted volume)
│   ├── sop/             # sop.docx + sop1–3.docx test cases; sop_truth.md
│   └── truth_set.json   # hand-annotated page-1 ground truth (59 nodes, 66 edges)
└── results/
    └── production/      # per-run eval output written by evaluate.py
```

### Frontend layout

```
frontend/src/
├── App.tsx              # root: job state machine, polling loop
├── api/client.ts        # typed fetch wrappers for all API endpoints
├── types/index.ts       # shared TS types (Job, Node, Edge, Violation, …)
└── components/
    ├── Graph.tsx         # react-cytoscapejs canvas; node click → NodeDetail
    ├── NodeDetail.tsx    # selected-node metadata + violation panel
    ├── Report.tsx        # SOP violation list
    └── StatusBar.tsx     # job status indicator
```


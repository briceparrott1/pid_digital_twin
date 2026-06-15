# P&ID to Digital Twin & SOP Cross-Referencing

A tool that automates cross-referencing P&ID diagrams against SOP documents, a painstaking process when done by hand. It solves two problems. First, it builds a graph-based digital twin of a P&ID in Neo4j. Second, it cross-references each SOP requirement against that twin using a mix of agentic and deterministic checks, flagging violations on the graph.

# tldr: 

I used a VLM based approach instead of learning approach because I found a paper that outlines a method where VLM based approach beat learning on a industry trained model, which I couldn't find anyway. I achieved a node detection F1 of 1.00 and connection topology of 0.45 on a manually created truth set of the first page of the given PI&D. SOP cross referencing is nearly 100% accurate for flagging inconsistent componenet specs and inconsistent parts, but occasionally introduces false positives and is overall bottlenecked by graph accuracy. Next steps would be putting this in a proces engineer's hands, creating more truth sets, benchmarking a learning approach to see which path to lean into, and learning more about computer vision and image processing methods. 

I have a new found apprecation for what you guys are doing because even making that one truth set sucked. 


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

Each selectable test case corresponds to one of the SOP documents in `computer_vision/data/sop/`. The expected violations for each case, meaning the ground truth of what the agent should flag, live in `computer_vision/data/sop/sop_truth/`. You can compare the generated report against the expected result for the case you ran.

The longest run I experienced was 4.5 minutes and $1.30 in tokens. This seemed to be an outlier, but because of the long and costly nature, I did not conduct signifcant testing of the entire pipeline. You might want to start a job, and then come back to this file. 

## Architecture

A monorepo with three apps: a FastAPI backend (`computer_vision`), a React/Vite/TS dashboard (`frontend`), and a dedicated R&D and eval sandbox for the extraction engine (`computer_vision_engine_dev`).

```
interface-take-home-monorepo/
├── .env                 # single env file shared by all apps
├── docker-compose.yaml  # neo4j + computer-vision + frontend
└── apps/
    ├── computer_vision/             # production FastAPI service
    ├── computer_vision_engine_dev/  # extraction-engine R&D + eval harness
    └── frontend/                    # dashboard
```

Docker Compose wires three services:

| Service | Build | Port | Notes |
|---|---|---|---|
| `neo4j` | `neo4j:5.18` | 7474 / 7687 | auth from `NEO4J_USER` / `NEO4J_PASSWORD` |
| `computer-vision` | `./apps/computer_vision` | 8000 | FastAPI; waits for healthy `neo4j` |
| `frontend` | `./apps/frontend` | 5173 | Vite dev server, proxies `/api` to the API |

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
        │     3-pass VLM engine      Claude → rules       │
        │     write nodes/edges → Neo4j                   │
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
   - `build_pid_graph` renders the PID PDF, runs the 3-pass extraction engine per page, concatenates nodes and connections, and writes them to Neo4j under this job.
   - `build_sop_requirements` parses `sop.docx` to text and sends it to Claude (`SOP_EXTRACTION_PROMPT`) to get a list of structured rules.
3. The LangGraph agent then checks each SOP requirement against the graph and writes violations back onto offending nodes.
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
├── main.py            # FastAPI routes
├── pipeline.py        # run_pipeline job orchestration
├── parsers/           # pid_parser (PDF→PNG), sop_parser (.docx→text)
├── extraction/        # SOP rule extraction + prompts
├── engine/            # the 3-pass CV+VLM extraction engine (see below)
├── services/          # build_pid_graph(), build_sop_requirements()
├── agent/             # LangGraph SOP-violation agent (see below)
└── db/                # neo4j_client, loader (writes), queries (reads)
```

### Frontend

A React/Vite/TS dashboard. On start job it posts to `/api/start-job`, polls `/api/report/{job_id}` every 3 seconds, and on completion fetches `/api/graph/{job_id}` and renders it with `react-cytoscapejs` (selectable nodes open a detail panel). `Report.tsx` shows the violation list.

## The extraction engine

The engine turns a raw P&ID page into a structured graph. It is a 3-pass pipeline. OpenCV handles preprocessing, segmentation, and pipe-line detection. A vision-language model (Claude, via the Anthropic SDK) handles all extraction. Everything is entered and orchestrated through `orchestrator.py::run_algo`.

The core idea, adapted from the literature (see [Approach](#approach--key-decisions)): a VLM can read a P&ID with no training data, but only if you do two things. First, segment the page so the model is not overwhelmed by the whole dense diagram at once. Second, give it the right view for each task. The 3 passes exist because nodes and connections want different conditions. Nodes read best on small clean crops, while connections need the whole image with the pipes visually traced. 

Pass by pass:

1. Render (`tools/render.py`): PyMuPDF renders the page to a high-res PNG at 375 DPI.
2. Preprocess (`tools/preprocess.py`): OpenCV contrast-enhancement (CLAHE), denoising, and sharpening produce two outputs, an `enhanced` image (sent to the VLM) and a `clean` binary mask (used by the CV steps).
3. Segment (`tools/segment.py`): finds high-detail regions via contour corners on the clean mask, merges overlapping boxes, then KMeans-clusters into k=5 crops. This was the change that took node recognition to 100% against the truth set.
4. Pass 1, Nodes: each of the 5 segment crops goes to Claude independently (`NODE_ONLY_PROMPT`) to extract equipment, instrument, valve, and out-of-system nodes with their metadata. No connections. Results are deduped and merged by `component_name`.
5. Line colorization (`tools/line_colorizer.py`): directional morphology and `HoughLinesP` detect pipe segments from the clean mask. Collinear runs are merged and snapped to horizontal or vertical, then each pipe is overlaid in a unique color with a `line_N` label. Produces the `color_coded` image and a `line_registry`.
6. Pass 2, Connections: the full color-coded image plus the node list from Pass 1 goes to Claude (`CONNECTION_PROMPT`). It traces pipes by color and geometry between known components, returning `connections` and 3-way `junctions`.
7. Pass 3, Equipment metadata: the full enhanced image goes to Claude (`EQUIPMENT_METADATA_PROMPT`) with the sole intent of reading equipment spec headers (size, design and operating pressure, temperature, MDMT, design capacity), which sit apart from the topology and are missed by density-based segmentation.
8. Resolve (`tools/resolve.py`): flattens nested `metadata` to `metadata_*` keys, normalizes `out_of_system` names, and merges the Pass 3 specs onto the equipment nodes.

The same engine lives in `apps/computer_vision/engine/` (production) and `apps/computer_vision_engine_dev/` (the R&D sandbox where prompt and CV changes are iterated and eval'd before being ported in). The dev orchestrator renders the PDF itself, while the production `run_algo(image)` takes page bytes directly. The two copies have diverged and are not currently kept in sync.

## The SOP cross-referencing agent

Once the graph exists, each SOP requirement has to be checked against it. This is done by a small LangGraph `StateGraph` rather than a fixed script. The reasoning: as SOPs grow in size and the kinds of requirements diversify, an agent with a growing toolset can decide how to validate each requirement, rather than us hard-coding a check per requirement type.

The agent state (`AgentState`) carries `job_id`, the `requirements` list, a `current_index`, a `violations_log`, and `messages`. A single node, `process_requirement`, loops over each requirement and dispatches on its type:

- `component_specifications`: a spec the components must satisfy, such as a pressure rating. The agent calls `query_components_by_name(pattern)` to find matching components, then for each one asks Claude (via `SPEC_CHECK_PROMPT`, with the `write_violation` tool bound) whether that component's `metadata_*` values violate the spec. The LLM step exists to resolve syntactic differences between how a value is written in the SOP versus on the P&ID and unify them under semantic meaning, for example `275 PSIG` versus `275 psi` versus a nested design-pressure field.
- `incompatible_components`: a rule that two component types must not be directly connected. The agent calls `query_incompatible_connections(type_a, type_b)`, which finds directed `CONNECTED_TO` edges between matching components purely in Cypher (no LLM), and writes a violation on both endpoints.

The two rule types deliberately exercise the two halves of the system. One leans on the VLM-extracted metadata, the other on the graph topology. The `incompatible_components` path is somewhat vestigial for this particular SOP, which contained no incompatibility rules and where component names are already unified under equipment, but I wanted to make use of having a graph db.

Tools (`agent/tools.py::make_tools(job_id)`), backed by `db/queries.py` and `db/loader.py`:

| Tool | Purpose |
|---|---|
| `query_components_by_name(pattern)` | Find components whose name matches a pattern |
| `query_incompatible_connections(type_a, type_b)` | Find direct `CONNECTED_TO` edges between two component types |
| `write_violation(...)` | Set `sop_violation = true` and append a message to `n.violation` on the matched node |

## Neo4j graph model

The graph is written by `db/loader.py` and read by `db/queries.py`.

- `(:Job {id, status, created_at})`: one per pipeline run. Created by `write_job`, status updated by `update_job_status`.
- Component nodes: `write_extraction` creates one node per extracted component, linked from the job as `(:Job)-[:CONTAINS]->(n)`. Properties are the flattened extraction fields:
  - `component_name`, `level` (`equipment`, `instrument`, `valve`, `junction`, or `out_of_system`)
  - `metadata_*` (flattened spec fields; nested dicts and lists are JSON-stringified)
  - `confidence`, `job_id`
  - `sop_violation: false`, `violation: null` (set later by the agent)
- Connections: `(a)-[:CONNECTED_TO {job_id, line_type, pipeline, ...}]->(b)`, resolved via an in-memory `component_name` to `elementId` map built during the same write.

```
(:Job)
   │ :CONTAINS
   ▼
(component)  ──:CONNECTED_TO {line_type, pipeline}──▶  (component)
  level: equipment|instrument|valve|junction|out_of_system
  component_name, metadata_*, confidence
  sop_violation, violation
```



## Approach & key decisions

To preface: I have no prior computer-vision experience. My strategy was to get a full-stack MVP standing, then iterate on graph accuracy, since that was clearly going to be the product's bottleneck.

Backend. I used a simple FastAPI backend, with one `main.py` fielding requests, a service layer for business logic, and all DB interaction contained in `db/loader` and `db/queries`. The cross-referencing is an agent rather than a script so that as SOP complexity grows, the agent can be given more tools and decide how best to validate each requirement (see [the agent section](#the-sop-cross-referencing-agent)).

The take-home suggested YOLO and Tesseract. I started there, but the data math rules it out. YOLO is a supervised, single-stage object detector that needs labeled training data, on the order of 150 to 200 labeled instances per class at the transfer-learning floor, across 15 to 20 distinct P&ID symbol classes, which is roughly 4,000 labeled instances. This dataset is 3 pages, less than 200 instances tota. A P&ID-domain-pretrained detector would be a real alternative, but I couln't find an available model. I found [a paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6083108) showing a training-free VLM pipeline outperforming an industry-trained model by using two interventions and decided to go with VLM. The region segmentation to counter attention dilution, and a line colorizer to record connections across segments. I adopted that approach.

How accuracy actually climbed. Node detection came together quickly, F1 0.70 at baseline, up to 0.92 with preprocessing and segmentation, and to 1.00 with prompt tuning. Connections were the hard part and started near 6%. I first implemented the paper's color-stitch method: overlay colored lines, record which colors each node touches per segment, then stitch connections back together across segments. It did not reach the accuracy they reported. I iterated on the stitching logic and prompts without significant gains. My hypothesis is that this particular P&ID exceeds the maximum visual entropy their method tolerates (they note this as a condition, though entropy is hard to compute exactly).

The two-pass redesign. That led to the current design: extract nodes from clean uncolored segment crops (Pass 1), then extract connections from the full colorized image with the known node list handed to the model (Pass 2). Seeing the whole pipe at once removed the broken-chain failures of per-segment stitching. The final connection gains came from error analysis rather than architecture. The model was proximity-guessing, connecting components to the nearest vessel instead of tracing the colored line, so explicit anti-proximity rules and modeling junctions strictly as 3-way tees moved the needle. A dedicated Pass 3 recovers equipment metadata from spec headers that sit in whitespace the density-based segmentation never crops. I implemented the third pass because I had mistakingly been ignoring metadata the entire time, and assumed the VLM would pick it up correctly if we were at 1.0 F1 for nodes. However, I was missing all eqiuipment level metadata because the K means clustering frequenlty would not pick the area of the pid that has equipment level specs. Furthermore, the K means clustering often uses up a segment on the bottom right info, which was not relevant to my graph, and from spot checking K means clustering segments, at least one segment in each group of 5 seemed to be wasted on a segment with only a few components. I didn't act on this because node F1 was at 1.OO, but there is definetely room to improve in the future (even if just compute / accuracy).

To correct the missing equipment metadata, I ended up implementing a 3rd pass where the VLM specifically looked for the equipment material. However, the VLM frequently gets slightly incorrect metadata, likely because it is processing an entire page rather than a focused segment. In the future, pass a focused segment of just the shot we are looking for would solve this. 

## Results

# Full pipeline 

I tested the full pipeline by creating 3 additional SOP docx files alongside the original:

- **Case 0** – The original SOP from the take-home assignment (baseline)
- **Case 1** – An SOP with altered operating specs that conflict with the P&ID
- **Case 2** – An SOP with a list of incompatible parts
- **Case 3** – An SOP combining the alterations from both Case 1 and Case 2

The full pipeline consistently detected every inconsistency across all four cases. In every failure I observed, the root cause was inaccurate graph data.

There was one recurring false positive: the VLM misread a dual-value temperature spec (e.g., `-20/400 F`) as a single concatenated number (`20400`). To fix this, I added the following clarification to the equipment metadata extraction prompt:

> "TEMPERATURE RANGES WRITTEN AS 'X/Y': design temp and MDMT are often printed
> together as a single MIN/MAX pair, e.g. 'MWP 350 PSIG @ -20/400 F'. This is
> TWO separate numbers, not one:
> - the lower (often negative) number → MDMT.temp_f
> - the higher number → design_specs.temp_f
>
> Example: '-20/400 F' means MDMT.temp_f = -20 and design_specs.temp_f = 400.
> NEVER concatenate the two numbers into one value (e.g. '-20/400' is NOT 20400)."

This resolved the issue. It's also a good example of the prompt-tuning-to-truth-data that I mention later. However, it is easily the most egregious example


The conclusion here is full pipeline (and really the ux) performance is bottle necked by graph accuracy.

# Engine

Full per-run metrics live in `apps/computer_vision_engine_dev/results/`, in `summary.md` (every metric per run) and `f1_summary.md` (the F1 trend). The condensed inflection points:

| Run | What changed | Node F1 | Conn topology F1 |
|---|---|---|---|
| run_1 | baseline | 0.70 | n/a |
| run_4 | + segmentation | 0.92 | n/a |
| run_7 | colored-line + per-segment stitch | 0.99 | n/a |
| run_14 | two-pass (connections first measured) | 1.00 | 0.19 |
| run_15 | + anti-proximity, 3-way junctions | 1.00 | 0.45 |
| run_20 | shipped config | 1.00 | 0.42 |

Node detection reached F1 1.00 and held there. It climbed from 0.70 to 1.00 quickly via segmentation and prompt tuning. Connection topology F1 (which only exists from run_14, see below for why) peaked at 0.45 and sits at 0.42 in the shipped config. That is the largest remaining gap.

Because the truth set is a single page, individual runs show real run-to-run variance. Reducing that variance with a larger, multi-page is a prioirty if I want to continue with VLM.




## Evaluation methodology

`apps/computer_vision_engine_dev/eval.py` scores each run against a hand-built truth set (`data/truth_set.json`, page 1, manually annotated: 59 nodes and 66 connections).

Every metric is built from three counts. A true positive is something predicted that is also in the truth set. A false positive is something predicted that is not in the truth set (a hallucination). 

- Precision is true positives divided by all predictions. Of what the system claimed, how much was right.
- Recall is true positives divided by all truth items. Of what actually exists, how much the system found.
- F1 is the harmonic mean of precision and recall. 

Node detection scores precision, recall, and F1 on `component_name`, per level and overall. Junctions and out-of-system nodes are excluded because their names are arbitrary or free text, not stable identities worth scoring.

### Connections, and why the metric changed

Connections are scored as F1 on (start, end) pairs, but the hard part is junctions. Junctions are structural points where three pipes meet. They have no real-world identity, and Pass 2 names them `j1`, `j2`, and so on non-deterministically, so the same physical junction can be `j5` in the truth set and `j12` in a prediction. We tried three ways of scoring, in this order:

- Fuzzy F1: drops any connection touching a junction and scores only direct component-to-component edges. Too narrow, it ignores most of the real topology, and it swings wildly between runs.
- Exact F1: matches (start, end) pairs with junction endpoints replaced by a generic token. The flaw is that it does not collapse chains, so `A → j1 → B` fails to match a truth-set `A → B` even though the connectivity is identical. 
- Topology F1 (the one we settled on): collapses junction chains into direct edges on both sides before comparing, so `A → j1 → j2 → B` becomes `A → B`. Two graphs that connect the same real components score as equal regardless of how junctions are labeled or chained.

I switched to topology because it measures the thing that actually matters, which is whether the right components end up connected, not whether two arbitrary junction labels happened to line up. Topology only exists from run_14 onward, which is when connection extraction became junction-aware, so earlier runs show n/a for it. Exact and fuzzy are kept only so those early runs stay comparable.

## Reflections & next steps

This was a cool project to work on. It was a largely uncharted problem space for me so got to learn a ton.

I have no way to benchmark pages 2 and 3 of the PID. Spot-checking their graphs, they look less accurate than page 1, which I would attribute to having tuned the prompts and the rest of the pipeline against feedback and eval metrics from page 1 alone semi-consciously. Equipment metadata extraction is in the same boat. It works, but it was not captured reliably across runs, so I am not putting a headline number on it.

My immediate next step would be to build truth data for pages 2 and 3 and measure eval accuracy there to get a normalized benchmark for the urrent VLM method. From there, I would put a hold on the VLM approach itself and try to aggregate usable data to fine-tune a model. If I could get the requisite data, I am guessing it would require much less effort to get to an mvp than to tune the VLM approach a bit (usually optimal to explore uncharted territory). Second, cost scales far better with a learned detector than with per-page VLM calls. If $1.30 produced an cross reference of acceptable quality to someone who pay for this, I am sure that sale could be made, but since the accuracy is not there, the continued development is not worth it untill exploring other methods. 

I also would get this in front of someone who would actually use it ASAP to see what is really important. Eg, I spent a ton of time fussing over how to represent and process junctions, but there is a chance they don't matter to someone in the field. 

## AI use 

I used agents to research, code, and even writes portions of this readme. My usual rule of thumb is I try not to use an agent for anything I couldn't do without reasonable documention because I think this will make me the best develoepr in the long run. For example, I know how to set up a route, service layer, and Neo4j query (if I'm looking at some cypher docs for complex queries lol), so I would not hesitate to have an agent do that for me. I know that I can verify the code it writes and find / debug in it if it fails. I blurred the line when having agents write portions of the engine that manipulated images. I understood the value each manipulation was supposed to enable, and how changing the values in those functions would affect the image, but I am confident there  are things I don't understand in my own codebase. To me, this is an acceptable trade off in a quick project because I had a means of eval, but definetly a gap I would need to fill in in order for me continue with image processing. 

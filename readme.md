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

Each selectable test case corresponds to one of the SOP documents in `computer_vision/data/sop/`. The expected violations for each case, meaning the ground truth of what the agent should flag, live in `/apps/computer_vision/data/sop/sop_truth/`. You can compare the generated report against the expected result for the case you ran.

The longest run I experienced was 4.5 minutes and $1.30 in tokens. This seemed to be an outlier, but because of the long and costly nature, I did not conduct signifcant testing of the entire pipeline. You might want to start a job, and then come back to this file (or do something else).

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

There was one recurring false positive: the VLM misread a dual-value temperature spec (e.g., `-20/400 F`) as a single concatenated number (`20400`). There is an occasional false positive where the VLM reads an operating temp spec as 255 instead of 250. To fix this, I added the following clarification to the equipment metadata extraction prompt:

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

---

# engine-v2

A recursive bisection pipeline for extracting P&ID graphs using a vision-language model (Claude Opus). This is a second attempt at the extraction problem, motivated by a misreading of the source paper in v1 and by wanting to see how far you can push a VLM-only approach without any learned component.

## Why come back

After v1, I realized I had misinterpreted the paper's algorithm. The paper was scoring connections on whether a node was assigned to the correct process unit, not whether a full directed graph of two-endpoint connections was reconstructed. I had been trying to build the harder thing. Once I understood that distinction, I wanted to measure it properly and see whether a VLM alone, given good segmentation and a clean prompt, could get there.

The thing that kept me going is that Claude genuinely understands P&IDs. It recognizes F-715A and F-715B as coalescing filters without being told. It correctly categorizes MV-, PSV-, and DPI- prefixes from convention alone. It handles the A/B bilateral symmetry of the diagram naturally. No training data required. The question is whether you can get it to be accurate enough given its limitations as a vision model.

## The core problem with single-call VLM

Tossing the full P&ID into one API call does not work well for two reasons.

First, there is too much visual information. The model has to simultaneously track 42 named components and 66 connections across a 5100x3300 px page. It consistently loses components at the periphery and transposes tags that look similar (MV-715-03A vs MV-715-03B).

Second, error probability compounds. Every additional component in the scene is another chance for attention drift, tag transposition, or a missed peripheral element. The wider the scene, the wider the distribution of possible outputs.

## Approach: recursive bisection

The paper's solution is K-means clustering to segment. I tried this but kept wasting segments on blank-space-heavy regions and the bottom-right title block.

Instead, the engine recurses. At each step, it evaluates every horizontal and vertical candidate cut position (every 2 pixels, within margins) and picks the one with the lowest cut cost: the sum of dilated-ink pixels in a band of width 5 centered on the line. Ink is dilated by a radius-3 kernel first, so cuts through or near drawn content are penalized more than cuts through whitespace. This reliably finds the column or row of whitespace between regions.

Recursion stops at a node when its minimum dimension falls below `min_dim`, its area falls below `min_area`, or its ink density falls below `min_ink_density` (treating the region as too sparse for a VLM call). Dense regions get a more aggressive size floor (`dense_min_dim`, `dense_min_area`) so packed areas get one additional cut before becoming leaves.

The cut strategy does not use overlap. Overlap doubles token costs at every boundary, makes deduplication non-trivial, and does not actually solve the stitching problem. Instead, the engine minimizes the number of elements a cut bisects. The aggregate cut cost of a full segmentation is the sum of cut costs at every active edge (the edges separating non-leaf nodes from their children). Lower aggregate cost means fewer drawn lines crossed, meaning fewer split nodes and connections to stitch.

To sweep 13,000+ stop-condition configurations efficiently, the cut tree is built once at maximum depth. Any parameter configuration is then evaluated in milliseconds by walking the pre-built tree, applying stop rules, and summing cut costs at the resulting active edges. The best configuration per segment count (7 to 25 leaves) was then run through the full VLM pipeline.

## Engine Architecture

The engine is a pure Python pipeline split across six packages under `src/engine/`.

**`preprocess/`** renders both the colored and uncolored PDFs to NumPy arrays at a shared DPI (300). The uncolored render is used for cut decisions (ink density, band cost); the colored render is sent to the VLM, since junction dots and pipe colors are encoded there.

**`cut/`** handles the geometry of finding and applying a cut:
- `cost_map.py` dilates the uncolored image by a radius-3 kernel, then computes a horizontal and vertical cost array: the sum of dilated ink across a band of width 5 at every candidate position.
- `best_cut.py` scans all candidate positions (every 2 px, within an edge margin) on both axes and returns the axis and position with the lowest cost.
- `split.py` slices the parent `Segment` at the cut position, producing two child `Segment`s. Each child knows which of its four sides are seams (internal cut boundaries) vs page edges, which the VLM uses to know where connections may continue off-crop.

**`recurse/`** is the recursive spine:
- `stop.py` checks the six stop conditions against a segment's dimensions, area, and ink density.
- `process.py` is a ~15-line recursive function: if `should_stop_cutting()`, call `leaf_reader(segment)` and wrap the result in a `Subgraph`; otherwise, call `best_cut` -> `split` -> recurse both halves -> `merge`. The leaf reader is injected, so the core recursion has no direct dependency on the VLM.

**`leaf/`** is the VLM boundary:
- `prompt.py` builds a structured prompt that tells the model exactly what JSON schema to return, with separate fields for fully-contained nodes and edges, connections that exit a crop boundary (`split_connections`), components bisected by the boundary (`split_nodes`), and lines that traverse the crop with no visible endpoint (`pass_through_connections`).
- `vlm_client.py` handles the Anthropic API: streaming calls (required at `max_tokens=32000`), exponential backoff on transport failures, and extraction of the text block from the response (excluding thinking blocks).
- `leaf_read.py` parses the raw VLM text into a typed `LeafResult`. A parse failure raises `LeafParseError`, which the sweep runner catches per-leaf and logs without aborting the run.

**`merge/`** resolves obligations at each seam as the recursion unwinds:
- `sides.py` defines which sides of a child segment face the cut and translates side labels from child frame to parent frame.
- `lines.py` pairs `SplitConnection` obligations by color within the facing set. Label is excluded from the pairing key because the VLM inconsistently omits it, and a label mismatch across a seam would cause a false split failure.
- `nodes.py` fuses `SplitNode` fragments (components bisected by the cut) until they are whole, then promotes them to resolved `Node`s.
- `dedupe.py` collapses duplicate node IDs that appear in both children.
- `merge.py` orchestrates all of the above for one cut: facing obligations are resolved or retired, non-facing obligations are retranslated to the parent frame and propagated up. An obligation that faces a seam and finds no partner is permanently retired into `failed_splits` rather than propagated. Once the region is enlarged past that seam, the obligation is interior and can never face a real boundary again.

**`graph.py`** collapses the root `Subgraph` into the final `PageGraph`. Any `open_connections` still alive at the root (obligations that reached the page edge without a partner) become `leftover_splits` in the diagnostics.

**`types.py`** holds all data contracts: `Box`, `Segment`, `Node`, `Edge`, `LeafResult`, `SplitConnection`, `PassThroughConnection`, `SplitNode`, `Subgraph`, `PageGraph`, and the `SELF_REF` sentinel used when a split node's own ID is not yet known at the time one of its edges is recorded.

**`config.py`** holds typed frozen dataclasses for each config domain (`StopConfig`, `CutConfig`, `RenderConfig`, `VlmConfig`), loaded from `config/defaults.yaml`.

The separation between the recursive spine, the cut geometry, the seam resolution, and the VLM boundary means each can be tested and modified independently.

## Baseline Comparison

Before running the full sweep, I ran two single-call baselines to understand what a raw VLM call can do on its own, without any segmentation.

I should have run these before starting. I ran the first baseline without extended thinking or tool use, which was a mistake in experimental design. When I later ran the baseline properly (with thinking and tool use enabled), the results were better and gave a clearer picture of the ceiling.

| run | description | node F1 | conn F1 |
|-----|-------------|---------|---------|
| run_baseline | single call, no thinking, no tool use | 0.927 | 0.873 |
| run_baseline_unlimited_tooling | single call, extended thinking + tool use | 0.965 | 0.910 |
| segs10 (best sweep) | 10-segment recursive bisection | 0.976 | 0.873 |

The honest conclusion: a single well-configured VLM call outperforms the segmented pipeline on connection topology (0.910 vs 0.873), and nearly matches it on node detection (0.965 vs 0.976). Segmentation helps nodes but hurts connections because more segment boundaries create more cross-boundary stitching failures.

Beyond raw accuracy, reviewing the unlimited-tooling run's errors revealed that some of what looked like model errors were actually annotation mistakes in the truth set. The model's actual accuracy is somewhat higher than these numbers suggest. Auditing and correcting the truth set is a known gap.

**Where segmentation still has a case.** Raw accuracy is not the only thing that matters in a production pipeline:

- *Error tracing*: every cut is deterministic. If a run fails or degrades, you can inspect exactly which leaf failed and why. With a single black-box call, a bad output is just a bad output.
- *Parallel execution*: all leaf crops are sent to the API simultaneously. A 10-segment run makes 10 concurrent API calls instead of one long serial call. For multi-page documents especially, this is meaningful.
- *Selective processing*: sparse regions can be given cheaper calls or skipped entirely, since ink density determines which regions get VLM attention.
- *Granular retry*: if one crop fails to parse, only that crop is retried. A parse failure on a single-call approach means retrying the whole page.
- *Scalability*: the recursion is page-agnostic. Multiple pages can be processed in parallel without any changes to the pipeline.

The segmented approach is a better engineering substrate even if it is not currently winning on the benchmark.

## Sweep Results

All 19 configurations ran clean (no parse errors). Ground truth: 42 non-junction nodes, 66 connections.

| segs | run    | node F1 | conn F1 |
|------|--------|---------|---------|
|    7 | run_31 |   0.976 |   0.857 |
|    8 | run_32 |   0.952 |   0.839 |
|    9 | run_33 |   0.952 |   0.864 |
|   10 | run_35 |   0.976 |   0.873 |
|   11 | run_36 |   0.976 |   0.855 |
|   12 | run_52 |   0.976 |   0.864 |
|   13 | run_38 |   0.964 |   0.816 |
|   14 | run_39 |   0.940 |   0.794 |
|   15 | run_40 |   0.940 |   0.780 |
|   16 | run_41 |   0.951 |   0.797 |
|   17 | run_42 |   0.951 |   0.813 |
|   18 | run_53 |   0.940 |   0.790 |
|   19 | run_44 |   0.951 |   0.780 |
|   20 | run_45 |   0.951 |   0.790 |
|   21 | run_46 |   0.929 |   0.760 |
|   22 | run_47 |   0.938 |   0.756 |
|   23 | run_54 |   0.938 |   0.689 |
|   24 | run_49 |   0.916 |   0.678 |
|   25 | run_50 |   0.952 |   0.750 |

**Best overall: segs10 (run_35), node F1 0.976, connection F1 0.873.**

The sweet spot is 7 to 12 segments. Beyond 13, both metrics decline: more boundaries mean more cross-boundary connections that must be stitched, and stitching errors accumulate. Precision is high across all configurations (node precision 0.93 to 0.98, connection precision 0.83 to 0.92). The model rarely invents nodes or connections. The challenge is recall.

## Common Misses

**Nodes missed in every run (19/19):**
- `MV-715-02`, the bypass valve at the inlet manifold. It sits at a T-junction between two other valves and was never identified across any configuration. The model appears unable to isolate it visually even when it occupies its own leaf segment.

**Nodes missed in most runs:**
- `TO CONDENSATE 2 PHASE SEPARATOR V-730` (14/19 runs): an off-diagram exit label where a pipe goes to the edge of the page with a text tag. The model either misses it or transcribes it as `V-73D` (OCR error, `0` read as `D`).
- `F-715B` (11/19 runs): the B-side coalescing filter. At higher segment counts, the filter vessel and its dense manifold get split across leaves in a way that confuses attribution. At lower counts (7 to 12 leaves), the whole B-side fits in one crop and is found reliably.
- `MV-715-08A` (3/19 runs): missed at specific segment counts where a cut bisects the valve's label from its symbol.

**Systematic hallucinations:**
- `MV-715-04A` (6/19 runs): does not exist. Only `MV-715-04B` is on the diagram. The model infers the A-side from the diagram's bilateral symmetry and is wrong; there is an asymmetry between the A and B inlet manifolds at that position.
- `TO CONDENSATE 2 PHASE SEPARATOR V-73D` (3/19 runs): the OCR error above, appearing as a hallucination when the true tag is also missed.
- `TUBING` (3/19 runs): a pipe material annotation treated as a node ID.

## Connection Patterns

In the best run (segs10), 11 of 66 connections were missed and 5 were hallucinated. Of the 11 false negatives, 9 involved a junction endpoint. The model correctly identifies the valves and equipment but sometimes fails to represent the full routing through the junction network.

The most common specific miss was `MV-715-10A`, which appears in two separate true connections (it connects on both sides to different junctions), with the model capturing only one of the two paths.

The most common hallucination pattern is A/B confusion: misassigning a connection to the A-side filter when it belongs to the B-side, or vice versa. This is a direct consequence of the diagram's strong bilateral symmetry.

## What Works, What Doesn't

The approach is effective at reading individual components from image crops. The model correctly identifies equipment tags, valve designations, instrument tags, and out-of-system references with high precision. It understands semantic categories without prompting.

The harder problem is the piping network: junction routing, split connections across segment boundaries, and the asymmetric details that break the bilateral symmetry the model expects. A post-processing pass that validates the merged graph against known P&ID conventions (e.g., every valve should have exactly two pipe connections) could recover some of the missed connections without any additional VLM calls.

The truth set itself is a weak point. This benchmark is a single manually annotated page, and reviewing the unlimited-tooling run revealed that some apparent model errors were actually annotation mistakes. All F1 numbers reported here should be treated as approximate, and the real accuracy is likely slightly higher. This is a known issue.

## Next Steps

1. **Audit the truth set.** Some of what looks like model error is annotation error. Fix the ground truth before drawing further conclusions from the F1 numbers.

2. **Fix the stitch quality.** The main accuracy gap against a single-call VLM is in connection stitching across segment boundaries. One option: after building the merged graph, pass the full image back to the model with the partial graph as context and ask it to validate or fill in missing connections. This would combine the node-reading advantages of segmentation with the full-topology view of a single call.

3. **Enable thinking on the sweep.** All 19 segmented runs used `thinking_effort=high` but were not run against the proper baseline (thinking + tools, single call) until after the sweep completed. The right comparison would be the same thinking configuration on both sides.

4. **Multi-page benchmark.** The entire pipeline has been tuned against one page. Build truth sets for pages 2 and 3 to measure generalization and reduce the variance from single-page evaluation.

5. **Consider a learned detector.** At some point, iterating on the VLM approach has diminishing returns. A fine-tuned detector trained on enough labeled P&ID data would be cheaper per page and more consistent. The current pipeline produces reasonable labeled data as a side effect of running, which could seed that training set.

## A third approach: code execution tooling

After the engine-v2 sweep showed that a single well-configured VLM call could nearly match segmentation on nodes and beat it on connections, the logical next question was whether pushing further in that direction made sense. The approach: upload the raw PDF to the Anthropic Files API, give the model the `code_execution` tool, and instruct it to write its own Python to rasterize the page at high DPI, slice it into overlapping tiles, and view each tile before transcribing anything. No client-side preprocessor. No fixed segmentation. The model decides what to look at and when to zoom in.

On paper this should produce better accuracy than anything else in this repo. In practice, a single run burned $60 in tokens in under six minutes and was killed before it finished.

The problem is there is no cost ceiling built into the approach. You pay for thinking tokens, for each tool call round trip, and for however many image crops the model decides to generate. That last number is not bounded. A denser page, more junctions, or a more cautious model would just cost more. There is no way to know what a run will cost before it finishes.

This makes the case for deterministic segmentation more concretely than the benchmark numbers did. With recursive bisection, the cost of a run is the number of leaves times the cost of one leaf call. You can estimate it before you start, cap it by capping the segment count, and parallelize it. The code-execution approach offers better accuracy in theory but no predictable spend in practice, which is a real problem if you want to run this on more than one page.

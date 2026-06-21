# Approach, Design & Reflections

## The extraction engine

The engine turns a raw P&ID page into a structured graph. It is a 3-pass pipeline. OpenCV handles preprocessing, segmentation, and pipe-line detection. A vision-language model (Claude, via the Anthropic SDK) handles all extraction. Everything is entered and orchestrated through `orchestrator.py::run_algo`.

The core idea, adapted from the literature (see [Approach & key decisions](#approach--key-decisions)): a VLM can read a P&ID with no training data, but only if you do two things. First, segment the page so the model is not overwhelmed by the whole dense diagram at once. Second, give it the right view for each task. The 3 passes exist because nodes and connections want different conditions. Nodes read best on small clean crops, while connections need the whole image with the pipes visually traced.

Pass by pass:

1. Render (`tools/render.py`): PyMuPDF renders the page to a high-res PNG at 375 DPI.
2. Preprocess (`tools/preprocess.py`): OpenCV contrast-enhancement (CLAHE), denoising, and sharpening produce two outputs, an `enhanced` image (sent to the VLM) and a `clean` binary mask (used by the CV steps).
3. Segment (`tools/segment.py`): finds high-detail regions via contour corners on the clean mask, merges overlapping boxes, then KMeans-clusters into k=5 crops. This was the change that took node recognition to 100% against the truth set.
4. Pass 1, Nodes: each of the 5 segment crops goes to Claude independently (`NODE_ONLY_PROMPT`) to extract equipment, instrument, valve, and out-of-system nodes with their metadata. No connections. Results are deduped and merged by `component_name`.
5. Line colorization (`tools/line_colorizer.py`): directional morphology and `HoughLinesP` detect pipe segments from the clean mask. Collinear runs are merged and snapped to horizontal or vertical, then each pipe is overlaid in a unique color with a `line_N` label. Produces the `color_coded` image and a `line_registry`.
6. Pass 2, Connections: the full color-coded image plus the node list from Pass 1 goes to Claude (`CONNECTION_PROMPT`). It traces pipes by color and geometry between known components, returning `connections` and 3-way `junctions`.
7. Pass 3, Equipment metadata: the full enhanced image goes to Claude (`EQUIPMENT_METADATA_PROMPT`) with the sole intent of reading equipment spec headers (size, design and operating pressure, temperature, MDMT, design capacity), which sit apart from the topology and are missed by density-based segmentation.
8. Resolve (`tools/resolve.py`): flattens nested `metadata` to `metadata_*` keys, normalizes `out_of_system` names, and merges the Pass 3 specs onto the equipment nodes.

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

The take-home suggested YOLO and Tesseract. I started there, but the data math rules it out. YOLO is a supervised, single-stage object detector that needs labeled training data, on the order of 150 to 200 labeled instances per class at the transfer-learning floor, across 15 to 20 distinct P&ID symbol classes, which is roughly 4,000 labeled instances. This dataset is 3 pages, less than 200 instances total. A P&ID-domain-pretrained detector would be a real alternative, but I couldn't find an available model. I found [a paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6083108) showing a training-free VLM pipeline outperforming an industry-trained model by using two interventions and decided to go with VLM. The region segmentation to counter attention dilution, and a line colorizer to record connections across segments. I adopted that approach.

How accuracy actually climbed. Node detection came together quickly, F1 0.70 at baseline, up to 0.92 with preprocessing and segmentation, and to 1.00 with prompt tuning. Connections were the hard part and started near 6%. I first implemented the paper's color-stitch method: overlay colored lines, record which colors each node touches per segment, then stitch connections back together across segments. It did not reach the accuracy they reported. I iterated on the stitching logic and prompts without significant gains. My hypothesis is that this particular P&ID exceeds the maximum visual entropy their method tolerates (they note this as a condition, though entropy is hard to compute exactly).

The two-pass redesign. That led to the current design: extract nodes from clean uncolored segment crops (Pass 1), then extract connections from the full colorized image with the known node list handed to the model (Pass 2). Seeing the whole pipe at once removed the broken-chain failures of per-segment stitching. The final connection gains came from error analysis rather than architecture. The model was proximity-guessing, connecting components to the nearest vessel instead of tracing the colored line, so explicit anti-proximity rules and modeling junctions strictly as 3-way tees moved the needle. A dedicated Pass 3 recovers equipment metadata from spec headers that sit in whitespace the density-based segmentation never crops. I implemented the third pass because I had mistakingly been ignoring metadata the entire time, and assumed the VLM would pick it up correctly if we were at 1.0 F1 for nodes. However, I was missing all equipment level metadata because the K-means clustering frequently would not pick the area of the P&ID that has equipment level specs. Furthermore, the K-means clustering often uses up a segment on the bottom right info block, which was not relevant to my graph, and from spot checking segments, at least one in each group of 5 seemed to be wasted. I didn't act on this because node F1 was at 1.00, but there is definitely room to improve in the future (even if just compute / accuracy).

To correct the missing equipment metadata, I ended up implementing a 3rd pass where the VLM specifically looked for the equipment material. However, the VLM frequently gets slightly incorrect metadata, likely because it is processing an entire page rather than a focused segment. In the future, passing a focused segment of just the area we are looking for would solve this.

## Engine v2: why come back

After v1, I realized I had misinterpreted the paper's algorithm. The paper was scoring connections on whether a node was assigned to the correct process unit, not whether a full directed graph of two-endpoint connections was reconstructed. I had been trying to build the harder thing. Once I understood that distinction, I wanted to measure it properly and see whether a VLM alone, given good segmentation and a clean prompt, could get there.

The thing that kept me going is that Claude genuinely understands P&IDs. It recognizes F-715A and F-715B as coalescing filters without being told. It correctly categorizes MV-, PSV-, and DPI- prefixes from convention alone. It handles the A/B bilateral symmetry of the diagram naturally. No training data required. The question is whether you can get it to be accurate enough given its limitations as a vision model.

## Engine v2: the core problem with single-call VLM

Tossing the full P&ID into one API call does not work well for two reasons.

First, there is too much visual information. The model has to simultaneously track 42 named components and 66 connections across a 5100x3300 px page. It consistently loses components at the periphery and transposes tags that look similar (MV-715-03A vs MV-715-03B).

Second, error probability compounds. Every additional component in the scene is another chance for attention drift, tag transposition, or a missed peripheral element. The wider the scene, the wider the distribution of possible outputs.

## Engine v2: recursive bisection approach

The paper's solution is K-means clustering to segment. I tried this but kept wasting segments on blank-space-heavy regions and the bottom-right title block.

Instead, the engine recurses. At each step, it evaluates every horizontal and vertical candidate cut position (every 2 pixels, within margins) and picks the one with the lowest cut cost: the sum of dilated-ink pixels in a band of width 5 centered on the line. Ink is dilated by a radius-3 kernel first, so cuts through or near drawn content are penalized more than cuts through whitespace. This reliably finds the column or row of whitespace between regions.

Recursion stops at a node when its minimum dimension falls below `min_dim`, its area falls below `min_area`, or its ink density falls below `min_ink_density` (treating the region as too sparse for a VLM call). Dense regions get a more aggressive size floor (`dense_min_dim`, `dense_min_area`) so packed areas get one additional cut before becoming leaves.

The cut strategy does not use overlap. Overlap doubles token costs at every boundary, makes deduplication non-trivial, and does not actually solve the stitching problem. Instead, the engine minimizes the number of elements a cut bisects. The aggregate cut cost of a full segmentation is the sum of cut costs at every active edge (the edges separating non-leaf nodes from their children). Lower aggregate cost means fewer drawn lines crossed, meaning fewer split nodes and connections to stitch.

To sweep 13,000+ stop-condition configurations efficiently, the cut tree is built once at maximum depth. Any parameter configuration is then evaluated in milliseconds by walking the pre-built tree, applying stop rules, and summing cut costs at the resulting active edges. The best configuration per segment count (7 to 25 leaves) was then run through the full VLM pipeline.

## Engine v2: where segmentation still has a case

Raw accuracy is not the only thing that matters in a production pipeline. Even though a single well-configured VLM call outperforms the segmented pipeline on connection topology (0.910 vs 0.873):

- *Error tracing*: every cut is deterministic. If a run fails or degrades, you can inspect exactly which leaf failed and why. With a single black-box call, a bad output is just a bad output.
- *Parallel execution*: all leaf crops are sent to the API simultaneously. A 10-segment run makes 10 concurrent API calls instead of one long serial call. For multi-page documents especially, this is meaningful.
- *Selective processing*: sparse regions can be given cheaper calls or skipped entirely, since ink density determines which regions get VLM attention.
- *Granular retry*: if one crop fails to parse, only that crop is retried. A parse failure on a single-call approach means retrying the whole page.
- *Scalability*: the recursion is page-agnostic. Multiple pages can be processed in parallel without any changes to the pipeline.

The segmented approach is a better engineering substrate even if it is not currently winning on the benchmark.

## A third approach: code execution tooling

After the engine-v2 sweep showed that a single well-configured VLM call could nearly match segmentation on nodes and beat it on connections, the logical next question was whether pushing further in that direction made sense. The approach: upload the raw PDF to the Anthropic Files API, give the model the `code_execution` tool, and instruct it to write its own Python to rasterize the page at high DPI, slice it into overlapping tiles, and view each tile before transcribing anything. No client-side preprocessor. No fixed segmentation. The model decides what to look at and when to zoom in.

On paper this should produce better accuracy than anything else in this repo. In practice, a single run burned $60 in tokens in under six minutes and was killed before it finished.

The problem is there is no cost ceiling built into the approach. You pay for thinking tokens, for each tool call round trip, and for however many image crops the model decides to generate. That last number is not bounded. A denser page, more junctions, or a more cautious model would just cost more. There is no way to know what a run will cost before it finishes.

This makes the case for deterministic segmentation more concretely than the benchmark numbers did. With recursive bisection, the cost of a run is the number of leaves times the cost of one leaf call. You can estimate it before you start, cap it by capping the segment count, and parallelize it. The code-execution approach offers better accuracy in theory but no predictable spend in practice, which is a real problem if you want to run this on more than one page.

## Next steps

1. **Audit the truth set.** Some of what looks like model error is annotation error. Fix the ground truth before drawing further conclusions from the F1 numbers.

2. **Fix the stitch quality.** The main accuracy gap against a single-call VLM is in connection stitching across segment boundaries. One option: after building the merged graph, pass the full image back to the model with the partial graph as context and ask it to validate or fill in missing connections. This would combine the node-reading advantages of segmentation with the full-topology view of a single call.

3. **Enable thinking on the sweep.** All 19 segmented runs used `thinking_effort=high` but were not run against the proper baseline (thinking + tools, single call) until after the sweep completed. The right comparison would be the same thinking configuration on both sides.

4. **Multi-page benchmark.** The entire pipeline has been tuned against one page. Build truth sets for pages 2 and 3 to measure generalization and reduce the variance from single-page evaluation.

5. **Consider a learned detector.** At some point, iterating on the VLM approach has diminishing returns. A fine-tuned detector trained on enough labeled P&ID data would be cheaper per page and more consistent. The current pipeline produces reasonable labeled data as a side effect of running, which could seed that training set.

6. **Get it in front of a process engineer.** I spent a ton of time fussing over how to represent and process junctions, but there is a chance they don't matter to someone in the field. User feedback would reorder these priorities immediately.

## Reflections

This was a cool project to work on. It was a largely uncharted problem space for me so got to learn a ton.

I have no way to benchmark pages 2 and 3 of the PID. Spot-checking their graphs, they look less accurate than page 1, which I would attribute to having tuned the prompts and the rest of the pipeline against feedback and eval metrics from page 1 alone semi-consciously. Equipment metadata extraction is in the same boat. It works, but it was not captured reliably across runs, so I am not putting a headline number on it.

My immediate next step would be to build truth data for pages 2 and 3 and measure eval accuracy there to get a normalized benchmark for the current VLM method. From there, I would put a hold on the VLM approach itself and try to aggregate usable data to fine-tune a model. If I could get the requisite data, I am guessing it would require much less effort to get to an MVP than to tune the VLM approach a bit (usually optimal to explore uncharted territory). Second, cost scales far better with a learned detector than with per-page VLM calls. If $1.30 produced a cross-reference of acceptable quality to someone who would pay for this, I am sure that sale could be made, but since the accuracy is not there, the continued development is not worth it until exploring other methods.

## AI use

I used agents to research, code, and even write portions of this readme. My usual rule of thumb is I try not to use an agent for anything I couldn't do without reasonable documentation because I think this will make me the best developer in the long run. For example, I know how to set up a route, service layer, and Neo4j query (if I'm looking at some Cypher docs for complex queries lol), so I would not hesitate to have an agent do that for me. I know that I can verify the code it writes and find / debug in it if it fails. I blurred the line when having agents write portions of the engine that manipulated images. I understood the value each manipulation was supposed to enable, and how changing the values in those functions would affect the image, but I am confident there are things I don't understand in my own codebase. To me, this is an acceptable trade-off in a quick project because I had a means of eval, but definitely a gap I would need to fill in in order to continue with image processing.

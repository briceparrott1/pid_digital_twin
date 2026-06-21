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

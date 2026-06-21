# Findings

## Full pipeline

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

This resolved the issue. It's also a good example of the prompt-tuning-to-truth-data that I mention later. However, it is easily the most egregious example.

The conclusion here is full pipeline (and really the UX) performance is bottlenecked by graph accuracy.

## Engine (v1)

Full per-run metrics live in `apps/computer_vision/results/v1_dev/`, in `summary.md` (every metric per run). The condensed inflection points:

| Run | What changed | Node F1 | Conn topology F1 |
|---|---|---|---|
| run_1 | baseline | 0.70 | n/a |
| run_4 | + segmentation | 0.92 | n/a |
| run_7 | colored-line + per-segment stitch | 0.99 | n/a |
| run_14 | two-pass (connections first measured) | 1.00 | 0.19 |
| run_15 | + anti-proximity, 3-way junctions | 1.00 | 0.45 |
| run_20 | shipped config | 1.00 | 0.42 |

Node detection reached F1 1.00 and held there. It climbed from 0.70 to 1.00 quickly via segmentation and prompt tuning. Connection topology F1 (which only exists from run_14, see evaluation methodology for why) peaked at 0.45 and sits at 0.42 in the shipped config. That is the largest remaining gap.

Because the truth set is a single page, individual runs show real run-to-run variance. Reducing that variance with a larger, multi-page truth set is a priority if I want to continue with VLM.

## Evaluation methodology

`engine/evaluate.py` scores each run against a hand-built truth set (`data/truth_set.json`, page 1, manually annotated: 59 nodes and 66 connections).

Every metric is built from three counts. A true positive is something predicted that is also in the truth set. A false positive is something predicted that is not in the truth set (a hallucination).

- Precision is true positives divided by all predictions. Of what the system claimed, how much was right.
- Recall is true positives divided by all truth items. Of what actually exists, how much the system found.
- F1 is the harmonic mean of precision and recall.

Node detection scores precision, recall, and F1 on `component_name`, per level and overall. Junctions and out-of-system nodes are excluded because their names are arbitrary or free text, not stable identities worth scoring.

### Connections, and why the metric changed

Connections are scored as F1 on (start, end) pairs, but the hard part is junctions. Junctions are structural points where three pipes meet. They have no real-world identity, and the engine names them `j1`, `j2`, and so on non-deterministically, so the same physical junction can be `j5` in the truth set and `j12` in a prediction. We tried three ways of scoring, in this order:

- Fuzzy F1: drops any connection touching a junction and scores only direct component-to-component edges. Too narrow, it ignores most of the real topology, and it swings wildly between runs.
- Exact F1: matches (start, end) pairs with junction endpoints replaced by a generic token. The flaw is that it does not collapse chains, so `A → j1 → B` fails to match a truth-set `A → B` even though the connectivity is identical.
- Topology F1 (the one we settled on): collapses junction chains into direct edges on both sides before comparing, so `A → j1 → j2 → B` becomes `A → B`. Two graphs that connect the same real components score as equal regardless of how junctions are labeled or chained.

I switched to topology because it measures the thing that actually matters, which is whether the right components end up connected, not whether two arbitrary junction labels happened to line up. Topology only exists from run_14 onward, which is when connection extraction became junction-aware, so earlier runs show n/a for it. Exact and fuzzy are kept only so those early runs stay comparable.

## Engine (v2) — baseline comparison

Before running the full sweep, I ran two single-call baselines to understand what a raw VLM call can do on its own, without any segmentation.

I should have run these before starting. I ran the first baseline without extended thinking or tool use, which was a mistake in experimental design. When I later ran the baseline properly (with thinking and tool use enabled), the results were better and gave a clearer picture of the ceiling.

| run | description | node F1 | conn F1 |
|-----|-------------|---------|---------|
| run_baseline | single call, no thinking, no tool use | 0.927 | 0.300 |
| run_baseline_unlimited_tooling | single call, extended thinking + tool use | 0.965 | 0.910 |
| segs10 (best sweep) | 10-segment recursive bisection | 0.976 | 0.873 |

The honest conclusion: a single well-configured VLM call outperforms the segmented pipeline on connection topology (0.910 vs 0.873), and nearly matches it on node detection (0.965 vs 0.976). Segmentation helps nodes but hurts connections because more segment boundaries create more cross-boundary stitching failures.

Beyond raw accuracy, reviewing the unlimited-tooling run's errors revealed that some of what looked like model errors were actually annotation mistakes in the truth set. The model's actual accuracy is somewhat higher than these numbers suggest. Auditing and correcting the truth set is a known gap.

## Engine (v2) — sweep results

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

Full per-run metrics live in `apps/computer_vision/results/v2_dev/`.

## Common misses (v2)

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

## Connection patterns (v2)

In the best run (segs10), 11 of 66 connections were missed and 5 were hallucinated. Of the 11 false negatives, 9 involved a junction endpoint. The model correctly identifies the valves and equipment but sometimes fails to represent the full routing through the junction network.

The most common specific miss was `MV-715-10A`, which appears in two separate true connections (it connects on both sides to different junctions), with the model capturing only one of the two paths.

The most common hallucination pattern is A/B confusion: misassigning a connection to the A-side filter when it belongs to the B-side, or vice versa. This is a direct consequence of the diagram's strong bilateral symmetry.

## What works, what doesn't (v2)

The approach is effective at reading individual components from image crops. The model correctly identifies equipment tags, valve designations, instrument tags, and out-of-system references with high precision. It understands semantic categories without prompting.

The harder problem is the piping network: junction routing, split connections across segment boundaries, and the asymmetric details that break the bilateral symmetry the model expects. A post-processing pass that validates the merged graph against known P&ID conventions (e.g., every valve should have exactly two pipe connections) could recover some of the missed connections without any additional VLM calls.

The truth set itself is a weak point. This benchmark is a single manually annotated page, and reviewing the unlimited-tooling run revealed that some apparent model errors were actually annotation mistakes. All F1 numbers reported here should be treated as approximate, and the real accuracy is likely slightly higher. This is a known issue.

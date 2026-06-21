# Known gaps

## Dual-image alignment

`load_pair` (`preprocess/pipeline.py`) only checks that the colored/uncolored renders match in
pixel dimensions, and logs an edge-diff count as an informational signal. Equal dimensions plus a
low edge-diff count does not certify pixel-level registration — two independent PDF renders can
still drift by a few pixels. Not yet visually re-verified against the current real PDF pair. If
drift exists, a bbox computed on `image_uncolored` would crop the wrong region of `image_colored`.

## Untagged split-node + split-connection ("split component with a split edge")

When a `split_node` has no legible tag in a given crop *and* a separate line attached to it exits
the crop on another side (a `split_connection`), there's no way to identify which split_node that
connection belongs to. `resolve_connections` finalizes the `Edge` as soon as it pairs at a seam,
independent of when the split_node's own body-cut sides resolve — so if a different fragment later
reveals the real tag, this edge stays stuck referencing `""` and falls into the shared anonymous-node
bucket instead of reattaching to the now-known tag. Not a misattachment to an unrelated component,
but a fidelity loss beyond what `untagged_count` already captures. Candidate fix: per-fragment
placeholder ids plus a final global substitution pass in `graph.py`, deferred pending a decision —
see conversation/design notes.

## Two untagged split_nodes connecting directly within one crop

The `connects_to` mechanism (`split_nodes[]` schema, `SELF_REF` substitution in `merge/nodes.py`)
assumes the *other* end of a fully-visible connection has a real id. If both ends are split_nodes
with no legible tag, fully visible within the same crop, there's no id to put in `connects_to`
either direction. Rare; currently inexpressible (no worse than before the `connects_to` fix existed).

## Equipment name and symbol can land in different crops with no link between them

Confirmed (not hypothetical): equipment names can sit far from their symbol, with no leader line or
other visible connector, and no bound on how far apart they can land — they may not even share a
seam in the cut tree. The merge architecture (`sides` + `fuse()` in `merge/nodes.py`) only resolves
fragments that share a literal cut boundary, so a bare name with zero symbol pixels in its crop (and
an untagged symbol with zero name pixels in its crop) cannot be reconciled by the current mechanism
at all — there's no seam to pair them on. The prompt now reports a bare name with no symbol as a
regular tagged `node` with no edges (not a `split_node` — that would risk `fuse()`'s positional
pairing wrongly merging it with an unrelated fragment; not `uncertainty` either, since the tag is
real, structured identity worth keeping in the graph). This preserves the tag losslessly, but the
underlying reconciliation — attaching that named, edge-less node to its actual connections, which
live on an anonymous (`id=""`) node elsewhere with the real symbol and edges — is still unsolved.
Likely needs a page-wide post-merge pass (match named edge-less nodes to anonymous same-type nodes)
rather than anything seam-local.

## Cut/stop calibration is heuristic, not yet validated against ground truth

`min_split_fraction`, `min_ink_density`, `dense_density_threshold`, `dense_min_dim`/`dense_min_area`
were all calibrated by eyeballing density/component-count distributions on one real page
(`results/run_4`–`run_6`), not against a labeled ground truth of "correct" segment boundaries. They
may not generalize to pages with different layouts, line densities, or aspect ratios.

## No real VLM call has been made end-to-end yet

Every real run against `/data` so far has used `--no-vlm` (segmentation-only checks). The leaf
prompt's `split_connections`/`split_nodes`/`uncertainty` behavior has only been examined via one
hand-inspected hypothetical transcript (passed in by the user), not a live run. Checkpoint 4's
flagged risks — wrong/missing `split_connection` labels, `split_nodes` under-reporting at
boundaries, `uncertainty` underuse — remain unverified against real model output.

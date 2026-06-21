Added min_split_fraction=0.35 balance constraint to best_cut (prevents edge-hugging sliver cuts) and raised stop floor to min_dim=800/min_area=1e6 (sized for ~depth-4 recursion on a 300dpi page).

Depth distribution (cuts from root): mostly 3–6, not a hard ≤4:
  3 cuts: 2 leaves
  4 cuts: 9 leaves
  5 cuts: 4 leaves
  6 cuts: 4 leaves
  Size range: 350–3313px (wide because the page isn't square — some branches hit the floor on height
  while width is still large, e.g. one leaf is 3313×350, so it took longer to shrink that dimension).
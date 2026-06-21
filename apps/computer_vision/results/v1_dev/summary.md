# V1 Engine Dev Results

Source: `apps/computer_vision_engine_dev/results/`
Engine: 3-pass CV+VLM (KMeans segmentation)
Best result: Node F1 = 1.00, Connection topology F1 = 0.45 (run_15_2-pass-v4)

| run | description | model | node F1 | conn topology F1 | conn exact F1 | conn fuzzy F1 | timestamp |
|---|---|---|---|---|---|---|---|
| run_1_baseline | baseline | claude-opus-4-5 | 0.70 | — | 0.33 | 0.34 | 2026-06-14T20:00:59 |
| run_2_v2-prompt | v2-prompt | claude-opus-4-5 | 0.88 | — | 0.44 | 0.37 | 2026-06-14T21:06:54 |
| run_3_pre-processing-v1 | pre-processing-v1 | claude-opus-4-5 | 0.86 | — | 0.52 | 0.33 | 2026-06-14T21:36:18 |
| run_4_segmentation-v1 | segmentation-v1 | claude-opus-4-5 | 0.92 | — | 0.54 | 0.37 | 2026-06-14T21:54:59 |
| run_5_pre-processing-v2 | pre-processing-v2 | claude-opus-4-5 | 0.91 | — | 0.51 | 0.25 | 2026-06-14T22:15:20 |
| run_6_pre-processing-v3 | pre-processing-v3 | claude-opus-4-5 | 0.92 | — | 0.50 | 0.30 | 2026-06-14T22:22:39 |
| run_7_colored-line-prefiltering | colored-line-prefiltering+stitch | claude-opus-4-5 | 0.99 | — | 0.11 | 0.32 | 2026-06-15T02:44:18 |
| run_8_colored-line-prefiltering-v2 | colored-line-prefiltering-v2 | claude-opus-4-5 | 0.99 | — | 0.23 | 0.29 | 2026-06-15T02:53:07 |
| run_9_colored-line-prefiltering-v | colored-line-prefiltering-v | claude-opus-4-5 | 0.99 | — | 0.24 | 0.45 | 2026-06-15T02:57:13 |
| run_10_colored-line-prefiltering-v3 | colored-line-prefiltering-v3 | claude-opus-4-5 | 0.99 | — | 0.35 | 0.43 | 2026-06-15T03:01:08 |
| run_11_colored-line-prefiltering-v3 | colored-line-prefiltering-v3 | claude-opus-4-5 | 0.99 | — | 0.34 | 0.09 | 2026-06-15T03:03:48 |
| run_12_2-pass-v1 | 2-pass-v1 | claude-opus-4-5 | 0.96 | — | 0.41 | 0.41 | 2026-06-15T03:17:53 |
| run_13_2-pass-v1 | 2-pass-v1 | claude-opus-4-5 | 0.93 | — | 0.53 | 0.22 | 2026-06-15T03:29:47 |
| run_14_2-pass-v3 | 2-pass-v3 | claude-opus-4-5 | 1.00 | 0.19 | 0.53 | 0.24 | 2026-06-15T03:47:13 |
| run_15_2-pass-v4 | 2-pass-v4 | claude-opus-4-5 | **1.00** | **0.45** | 0.58 | 0.51 | 2026-06-15T03:57:21 |
| run_16_2-pass-v5 | 2-pass-v5 | claude-opus-4-5 | 1.00 | 0.36 | 0.68 | 0.36 | 2026-06-15T04:04:53 |
| run_17_merge_metadeta_on_dedupe | merge metadata on dedupe | claude-opus-4-5 | 0.99 | 0.42 | 0.64 | 0.56 | 2026-06-15T15:26:28 |
| run_18_merge_metadeta_on_dedupe-v2 | merge metadata on dedupe-v2 | claude-opus-4-5 | 0.99 | 0.33 | 0.59 | 0.30 | 2026-06-15T15:41:21 |
| run_19_merge_metadeta_on_dedupe-v3 | merge metadata on dedupe-v3 | — | FAILED | — | — | — | 2026-06-15T16:10:36 |
| run_20_merge_metadeta_on_dedupe-v3 | merge metadata on dedupe-v3 | claude-opus-4-5 | 1.00 | 0.42 | 0.49 | 0.28 | 2026-06-15T16:15:19 |

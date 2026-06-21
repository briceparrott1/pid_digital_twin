Prompt fixes (out_of_system verbatim id, equipment group heading, 0/D caution, instrument trailing-letter, tag-in-metadata/placeholder bans) + merge fix (unmatched facing obligations retire into failed_splits) + max_tokens 4096->8192 + parser tolerates missing top-level list keys + auto-capture raw response to parse_error.json on a future LeafParseError.

## Evaluation (run_13)

- Node F1 (junctions excluded): 0.769 (precision 0.833, recall 0.714, tp=30 fp=6 fn=12)
- Connection F1 (junction endpoints collapsed to category): 0.490 (precision 0.750, recall 0.364, tp=24 fp=8 fn=42)

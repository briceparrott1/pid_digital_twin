Enabled adaptive extended thinking (thinking.type=adaptive + output_config.effort=high, not the older budget_tokens shape -- this model rejected that) + max_tokens 8192->16000, to improve per-segment read accuracy via deliberate reasoning. No tool use.

## Evaluation (run_15)

- Node F1 (junctions excluded): 0.929 (precision 0.929, recall 0.929, tp=39 fp=3 fn=3)
- Connection F1 (junction endpoints collapsed to category): 0.684 (precision 0.784, recall 0.606, tp=40 fp=11 fn=26)

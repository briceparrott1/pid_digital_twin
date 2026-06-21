# CLAUDE.md — interface-take-home-monorepo

## What this repo is

A tool that automates cross-referencing P&ID (Piping & Instrumentation Diagram) documents against Standard Operating Procedures (SOPs). It builds a Neo4j graph-based digital twin from a P&ID PDF, then runs a LangGraph agent to flag SOP violations on the graph.

## Monorepo layout

```
apps/
├── computer_vision/          # Production FastAPI service (port 8000)
└── frontend/                # React/Vite/TS dashboard (port 5173)
docker-compose.yaml          # Starts neo4j + computer-vision + frontend
.env                         # Single env file shared by all apps (ANTHROPIC_API_KEY, NEO4J_*)
```

See `docs/architecture.md` for per-app internals, the extraction pipeline flow, and the Neo4j graph model. Read it when working inside a specific app.

## Quick start

```bash
cp .env.example .env   # fill in ANTHROPIC_API_KEY and NEO4J_PASSWORD
docker compose up      # neo4j:7474, API:8000, frontend:5173
```

Click "Start Job" in the frontend UI and select a test case. The pipeline runs asynchronously; poll `/api/report/{job_id}` for completion.

## Python code style (enforced)

- PEP 8, formatted with Black (88 cols), imports sorted by Ruff
- `ruff check .` and `black --check .` must pass
- Type hints on all public APIs
- No unused imports, prefer simple functions over complex ones

## Gotchas (always keep in mind)

- The truth set has annotation errors — audit before drawing strong conclusions from any F1 number.

(Further known gaps are documented per-app in `docs/architecture.md`.)

## Delegation

- Delegate to subagents (return only a summary or a file path, not raw output):
  - Eval runs (`engine/evaluate.py`) — these dump a lot of output; report
    back the config and the resulting F1 numbers only.
  - Codebase research across `apps/computer_vision/engine/` subpackages —
    e.g. "trace how a Segment flows from cut/ through recurse/ to merge/" —
    report key files and the summary.
  - Log/output processing and test runs.
- Keep in the main thread: implementation and any change where you need to
  reason across the whole pipeline.
- Heuristic: if a task touches more than ~5 files or would dump output you
  won't reference again, isolate it in a subagent.
- Scope research subagents to read-only tools (Read, Glob, Grep).
- For independent investigations, spawn parallel subagents — e.g. research
  cut/, merge/, and leaf/ simultaneously, then synthesize.




## Heavy lookups: always delegate to a subagent

Any task that loads a large skill, fetches docs, or reads a lot of files to
answer ONE factual question must run in a subagent — never in the main thread.
The skill/doc bulk stays in the worker; only the answer returns here.

This applies especially to the `claude-api` skill and any web-doc lookup. Do NOT
load `claude-api` (or other large skills) in the main conversation under any
circumstances.

### When to delegate
- A skill needs loading to answer a question (e.g. "what's the supported way to
  cap thinking on opus-4-8?").
- The answer requires fetching/searching external docs.
- Resolving the question means reading several files you won't reference again.

If the answer is already known or trivially findable, just answer — don't spawn a
worker for one-line facts.

### Delegation template
Spawn a subagent with this shape:

> Load the <skill-name> skill (or fetch <docs>). Determine: <the single specific
> question>. Return ONLY the answer — the exact parameter/value/shape and one
> line of context. No doc excerpts, no skill text, no file dumps. Max ~10 lines.
> Do not echo what you read to get there.

### Hard constraints on what comes back
- The worker returns a SUMMARY, not source material. The whole point is keeping
  this thread lean — a 2,000-token dump back into the parent defeats it.
- Cap the return at ~10 lines. If the answer genuinely needs more, the worker
  returns the answer plus a pointer (file path / doc section), not the content.
- One question per subagent. Don't batch unrelated lookups into one worker.

### Example (the recurring case)
> Spawn a subagent: load the `claude-api` skill, find the supported way to cap or
> disable extended thinking on `claude-opus-4-8` (budget_tokens vs effort level),
> and return ONLY the correct parameter shape with one line of context. Do not
> load this skill in the main thread.

Expected return: a few lines like "opus-4-8 uses adaptive thinking + effort;
cap via effort: low|medium|high, not budget_tokens" — nothing more.
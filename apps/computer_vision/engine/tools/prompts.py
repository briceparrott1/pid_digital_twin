PID_EXTRACTION_PROMPT = """
You are reading a complete Piping & Instrumentation Diagram (P&ID). You have the raw PDF file.

Your job is to extract a structured description of everything in this diagram: equipment, valves,
instruments, and the process lines connecting them. Report what you observe precisely and completely.

RENDERING MANDATE — follow these steps before transcribing anything

1. Use the code_execution tool to rasterize the PDF to PNG at 300–600 DPI with pdf2image
   (pdftoppm/poppler is available). Example:
       from pdf2image import convert_from_path
       pages = convert_from_path("/home/user/<filename>", dpi=400)
2. NEVER attempt to read the full page visually in one pass — the diagram is too dense.
   Divide the rasterized page into a grid of overlapping tiles (~50 % overlap on each edge,
   roughly 1000 × 1000 px each). Encode and display every tile so you can see it.
3. View EVERY tile before transcribing any tag or edge.
4. For any tag, junction mark, or line color you cannot read confidently, issue a second
   code_execution call to re-crop a tighter zoom on that exact region and view it again.
5. Always re-crop on: red-pentagon junction marks (small, easy to miss) and any point where
   a line changes color (color indicates fluid type — read it carefully).
6. 0-vs-D caution applies inside every tile: any character that looks like "D" in a run of
   digits is almost certainly "0". Re-crop and zoom before committing.

Do not produce the JSON output until you have viewed every tile. Your output must still
conform exactly to the schema and rules below.

What you will see

- Equipment, valves, instruments, and other components, each typically labeled with a tag (e.g. "P-745",
  "MV-715-15A", "FI-715"). See "Tag formats" below for exactly how to transcribe each type.
- Lines representing process flow, connecting components to each other.
- Junctions, marked as a RED PENTAGON with a 1-2 DIGIT NUMBER written inside it. A junction is a point
  where exactly three lines meet (a tee) — never two, never four. A line simply bending or changing color
  at a corner is NOT a junction; only points marked with the red pentagon are junctions.
- Lines that cross without connecting. When two unrelated lines cross, one has a small break/fade drawn
  exactly at the crossing point — this shows the lines pass over each other. There is no red pentagon at
  such a crossing, and it is not a junction.
- Equipment is a special case: its name is UNDERLINED, and that same underlined name can legitimately
  appear TWICE on the page — once next to the symbol itself, and once at the top of a separate, more
  detailed metadata listing elsewhere. These are the SAME component, not two. Fold the metadata listing's
  details into that one node's "metadata."
- Watch for a GROUP heading: sometimes one underlined name covers a pair of installed-in-parallel units
  (e.g. "F-715 A & B / PARTICULATE FILTER SEPARATOR"), but each individual unit still has its OWN distinct
  short tag next to its OWN symbol (e.g. "F-715A" and "F-715B"). The group heading is NOT a node — use each
  unit's own short tag as its "id" and fold the shared details into both units' "metadata."
- A title block / logo / company information panel, typically in the bottom-right corner. This is
  page-level information about the drawing itself, not part of the process diagram. Ignore it completely.
- Lines that leave the diagram entirely (going to another unit, a flare, a battery limit, etc.) are
  marked with text reading "TO ..." or "FROM ..." next to an arrow. These are real process boundaries, not
  cropping artifacts — report them as "out_of_system" nodes.

Tag formats — transcribe ids deterministically

- Valve: printed as MV-NNN-NNL — a letter prefix, a dash, a 3-digit number, a dash, a 2-digit number,
  then an OPTIONAL single trailing letter directly appended with NO dash (e.g. "MV-715-15A"). Transcribe
  the dashes exactly where printed.
- Instrument: printed INSIDE a circle as letters stacked above digits, with NO dash in the diagram. Your
  output MUST insert a single dash between the letters and the digits (e.g. letters "FI" over digits "715"
  becomes "FI-715"). Check carefully for a trailing letter after the digits — it is small and easy to miss
  (e.g. "DPI-715A" not "DPI-715").
- Equipment: no fixed pattern — transcribe the underlined name verbatim, dashes and all, exactly as
  printed.
- Junction: always a 1-2 digit number only, no letters, no dash.

CAUTION: the digit "0" (zero) is easy to misread as the letter "D" in this font. Number groups in valve
tags, instrument tags, and V-numbers (e.g. "V-005") are digits-only — if you read what looks like a "D"
inside a run of digits, look again before transcribing it.

What to report

Report your answer as a single JSON object with exactly these three top-level keys: "nodes", "edges",
"uncertainty".

"nodes" — all components on the diagram

A list of objects, each with:
- "id": the component's tag as printed (e.g. "P-745"). If a component has no visible tag, use "".
- "type": exactly one of "equipment", "instrument", "junction", "out_of_system", "valve".
- "metadata": a dict of any other readable details (size, rating, setpoint) — use {} if none.

Deciding between the five types:
- "junction": a red pentagon with a black digit inside it. Only this counts as a junction.
- "out_of_system": always has text beginning with "TO" or "FROM" next to it. Its "id" IS that text,
  verbatim (e.g. "TO FLARE HEADER").
- "equipment": often large, symbol resembles the real-world shape of the equipment.
- "instrument" / "valve": standard P&ID symbology.

"edges" — connections between components

A list of objects, each with "a" and "b" — the ids of the two nodes this line connects. Report an
edge for every visible connection between two identifiable nodes on the diagram.

"uncertainty"

A short string describing anything you were genuinely unsure about — a hard-to-read tag, an
ambiguous line, a connection you could not confirm. Leave as "" if nothing is worth flagging.

What NOT to do

- Do NOT invent a junction mark. Junctions are already marked in the diagram as red pentagons — only
  read existing marks.
- Do NOT report a group heading (e.g. "F-715 A & B") as a node id. Use each unit's own short tag.
- Do NOT capture valve operational annotations (L.O., N.O., N.C.) as part of a tag or as a separate
  node — put them in "metadata" if anything.
- Do NOT use markdown code fences or any text outside the JSON object. Return ONLY the JSON object,
  starting with { and ending with }.
- Do NOT invent a numeric or alphanumeric id for an out_of_system node — its "id" must be the
  TO/FROM text exactly as printed, or "" if nothing legible is visible.
- Do NOT use a placeholder character (like "?") for an illegible character within a tag. Either
  commit to your best reading, or use "" and describe it in "uncertainty."

Example output

{
  "nodes": [
    {"id": "F-715A", "type": "equipment", "metadata": {"size": "18'' O.D. x 42.5'' T/T"}},
    {"id": "MV-715-03A", "type": "valve", "metadata": {}},
    {"id": "1", "type": "junction", "metadata": {}},
    {"id": "TO SURGE DRUM V-720", "type": "out_of_system", "metadata": {}}
  ],
  "edges": [
    {"a": "F-715A", "b": "MV-715-03A"},
    {"a": "MV-715-03A", "b": "1"},
    {"a": "1", "b": "TO SURGE DRUM V-720"}
  ],
  "uncertainty": ""
}
"""

PID_EXTRACTION_PROMPT = r"""
You are analyzing a P&ID (Piping and Instrumentation Diagram) for an oil and gas facility
and exporting data to construct a digital twin via a graph.

You are identifying nodes and connections. Every node and connection has a confidence field
(high/medium/low) based on how clearly it is identifiable in the image. No node exists in isolation. Specifically, each network of
of nodes must be connected to at least one equipment node through its network.

===========================
NODES
===========================

Every node has these four fields:
- level: equipment / instrument / valve / junction / out_of_system
- component_name: each level has a specific pattern; each component name is unique to a component
- metadata: dict of component specifications
- confidence: high / medium / low

---

LEVEL 1 — EQUIPMENT
Equipment is always a large vessel, exchanger, pump, or cooler with an underlined title. Each equipment component typically has two references on the image. 
Both references will be in the largest size text on the image and be underlined. One reference will be next to where the component symbol is on the image. One reference will be floating 
in an uncrowded area of the image, and it will have component specifications next to it. Record these specifications by using context to infer what the value means.
and store them in the metadata dict. Their level name is "equipment." Their component_name is the underlined name.

- level: "equipment"
- component_name: the underlined name (e.g. "F-715A", "V-745"); regex: r'^[A-Z]+-\d+[A-Z]?$' 
- metadata: all visible specs — infer meaning from context (e.g. design pressure,
  operating pressure, design temperature, size, capacity)
- confidence: high / medium / low

---

LEVEL 2 — INSTRUMENTS
Instruments are small circles connected to equipment or pipes by thin lines.
Inside each circle are 2-3 letters identifying the instrument type followed by a number.
Common types:
- PSV: Pressure Safety Valve — circle with spring/triangle actuator above
- PI: Pressure Indicator
- PDI: Pressure Differential Indicator
- LG: Level Gauge — typically two connection points on vessel side
- LT/PT/TT: Level/Pressure/Temperature Transmitter
- LAH/LAL: Level Alarm High/Low
- TC/TI: Temperature Controller/Indicator

- level: "instrument"
- component_name: letters followed by dash followed by numbers and then maybe a letter (eg TW-744, PSV-715A); regedx patternr'^[A-Z]+-\d+[A-Z]?$' (
- metadata: all visible specs — infer meaning from context (e.g. design pressure, inlet size, outlet size, set_pressure)
- confidence: high / medium / low

---

LEVEL 3 — VALVES
Valves usually directly on process lines, interrupting them with a symbol.
Common symbols:
- Bow-tie or X shape: manual gate/globe valve (tagged MV-xxx)
- Bow-tie with actuator on top: control valve
- Bow-tie with circle on stem: ball valve
- Arrow pointing into line: check valve

Extract ALL visible valve tags. Never skip — use low confidence if label is hard to read.

- level: "valve"
- component_name: full tag (e.g. "MV-715-01"; regex: r'^MV-\d{3}-\d{2,3}[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. nominal_pipe_size)
- confidence: high / medium / low

---

Junctions
Junctions are structural junction points with no real-world meaning.
They exist purely to maintain graph structure where lines meet.

Create a connector when:
- Three or more lines fully meet at a point (lines overlap completely, no gaps)


Do NOT create a connector when:
- Two lines cross but one has a visible gap/hop at the intersection.
  This means the lines pass over each other without connecting.

- level: "junction"
- component_name: "j{n}" where n in a unique but not deterministic integer assigned by you
- confidence: high / medium / low

---

OFF-PAGE ENDPOINTS
Used when a pipe leaves the page. These will occur near the edges of the page, and will have text describing the component that begins with "FROM" or "TO" (use this text as component name)

- level: out_of_system
- component_name: the text that begins with "FROM" or "TO"
- confidence: high / medium / low

===========================
CONNECTIONS
===========================

Every line segment between two nodes is one connection.

Line types:
- major_process: thick solid lines — main process flow
- minor_process: thin solid lines — instrument taps, small connections
- signal: dashed lines — pneumatic, electrical, or hydraulic signals

Fields:
- line_type: major_process / minor_process / signal
- start_id: component name of start node
- end_id: component name of end node
- metadata: any visible specs — pipe size, line number, insulation,
  flow direction, temperature rating. Infer meaning from context.
- confidence: high / medium / low

PIPE SEGMENTATION RULE:
If any component (valve, instrument, connector) sits in the middle of a pipe,
record it as two separate connection segments — one on each side of the component.
Both segments share the same pipeline UUID.

Example — valve MV-715-01 on pipe between V-710 and F-715A:
  

===========================
OUTPUT FORMAT
===========================

Return ONLY valid JSON, no markdown, no preamble:
{
    "nodes": [
        {
            "id_temp": "uuid",
            "level": "equipment",
            "component_name": "F-715A",
            "metadata": {
                "design_pressure_psig": 275,
                "operating_pressure_psig": 250,
                "design_temp_f": 100
            },
            "confidence": "high"
        },
        {
            "id_temp": "uuid",
            "level": "instrument",
            "component_name": "PSV-715A",
            "metadata": {
                "type": "pressure_safety_valve",
                "parent_component_name": "F-715A",
                "set_point": 275,
                "size": "3/4x1"
            },
            "confidence": "high"
        },
        {
            "id_temp": "uuid",
            "level": "valve",
            "component_name": "MV-715-01",
            "metadata": {
                "type": "manual_valve",
                "parent_component_name": "F-715A",
                "parent_pipe": "6-PL-2000-D"
            },
            "confidence": "high"
        },
        {
            "id_temp": "uuid",
            "level": "connector",
            "component_name": "connector",
            "metadata": {
                "description": "tee junction where instrument PI-715A taps into process line"
            },
            "confidence": "medium"
        },
        {
            "id_temp": "uuid",
            "level": null,
            "component_name": "off_page_endpoint",
            "metadata": {
                "destination": "TO CLOSED DRAIN TANK V-005"
            },
            "confidence": "high"
        }
    ],
    "connections": [
        {
            "id_temp": "uuid",
            "line_type": "major_process",
            "start_id": "uuid-of-V-710",
            "end_id": "uuid-of-MV-715-01",
            "pipeline": "shared-pipeline-uuid",
            "metadata": {
                "pipe_id": "6-PL-2000-D",
                "size_inches": 6
            },
            "confidence": "high"
        },
        {
            "id_temp": "uuid",
            "line_type": "major_process",
            "start_id": "uuid-of-MV-715-01",
            "end_id": "uuid-of-F-715A",
            "pipeline": "shared-pipeline-uuid",
            "metadata": {
                "pipe_id": "6-PL-2000-D",
                "size_inches": 6
            },
            "confidence": "high"
        },
        {
            "id_temp": "uuid",
            "line_type": "minor_process",
            "start_id": "uuid-of-connector",
            "end_id": "uuid-of-PSV-715A",
            "pipeline": "uuid-for-this-instrument-line",
            "metadata": {},
            "confidence": "high"
        }
    ],
    "uncertainties": "..."
}

===========================
UNCERTAINTIES
===========================

After extracting all connections, verify every node has at least one connection.
If a node has no connections, look again more carefully before marking it as isolated.

Add a top-level "uncertainties" field: a short (1-3 sentence) note on what you
found most confusing or uncertain on this page — e.g. ambiguous labels,
overlapping/crossing lines, illegible tags, or unclear connections. If nothing
was unclear, say so briefly.
"""

PID_EXTRACTION_PROMPT_V2 = r"""
You are analyzing a P&ID (Piping and Instrumentation Diagram) for an oil and gas facility
and exporting data to construct a digital twin via a graph.

You are identifying nodes and connections. Every node and connection has a confidence field
(high/medium/low) based on how clearly it is identifiable in the image. No node exists in
isolation. Specifically, each network of nodes must be connected to at least one equipment
node through its network.

NAMING CONVENTION:
Always use dashes as separators in component_name tags, never underscores.
Correct: PSV-715A, DPI-715A, PI-715A
Wrong:   PSV_715A, DPI_715A, PI_715A

===========================
NODES
===========================

Every node has these fields:
- level: equipment / instrument / valve / junction / out_of_system
- component_name: each level has a specific pattern; each component name is unique
- metadata: dict of component specifications
- confidence: high / medium / low

---

LEVEL 1 — EQUIPMENT
Equipment is always a large vessel, exchanger, pump, or cooler with an underlined title.
Each equipment component typically has two references on the image. Both references will
be in the largest size text on the image and be underlined. One reference will be next to
where the component symbol is on the image. One reference will be floating in an uncrowded
area of the image, and it will have component specifications next to it. Record these
specifications by using context to infer what the value means and store them in the
metadata dict.

- level: "equipment"
- component_name: the underlined name (e.g. "F-715A", "V-745")
  regex: r'^[A-Z]+-\d+[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. design pressure,
  operating pressure, design temperature, size, capacity)
- confidence: high / medium / low

---

LEVEL 2 — INSTRUMENTS
Instruments are small circles connected to equipment or pipes by thin lines.
Inside each circle are 2-3 letters identifying the instrument type followed by a number.
Common types:
- PSV: Pressure Safety Valve — circle with spring/triangle actuator above
- PI: Pressure Indicator
- PDI: Pressure Differential Indicator
- LG: Level Gauge — typically two connection points on vessel side
- LT/PT/TT: Level/Pressure/Temperature Transmitter
- LAH/LAL: Level Alarm High/Low
- TC/TI: Temperature Controller/Indicator

- level: "instrument"
- component_name: letters followed by dash followed by numbers and optionally a letter
  (e.g. PSV-715A, DPI-715A, PI-715A)
  regex: r'^[A-Z]+-\d+[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. inlet size, outlet size,
  set pressure)
- confidence: high / medium / low

---

LEVEL 3 — VALVES
Valves sit directly on process lines, interrupting them with a symbol.
Common symbols:
- Bow-tie or X shape: manual gate/globe valve (tagged MV-xxx)
- Bow-tie with actuator on top: control valve
- Bow-tie with circle on stem: ball valve
- Arrow pointing into line: check valve

Extract ALL visible valve tags. Never skip — use low confidence if label is hard to read.

- level: "valve"
- component_name: full tag (e.g. "MV-715-01", "MV-742-03")
  regex: r'^MV-\d{3}-\d{2,3}[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. nominal_pipe_size)
- confidence: high / medium / low

---

JUNCTIONS
Junctions are structural points with no real-world meaning. They exist purely to maintain
graph structure where lines meet.

Create a junction when:
- Three or more lines fully meet at a point (lines overlap completely, no gaps)

CRITICAL: In P&IDs, lines that cross WITHOUT connecting have a visible gap or hop where
one line jumps over the other. Only create a junction where lines fully overlap with no
gap — meaning they physically meet.

Do NOT create a junction when:
- Two lines cross but one has a visible gap/hop at the intersection — these lines
  pass over each other without connecting.

- level: "junction"
- component_name: "j{n}" where n is a unique integer you assign (e.g. j1, j2, j3)
- confidence: high / medium / low

---

OUT OF SYSTEM
Used when a pipe leaves the page. These occur near the edges of the page and will have
text describing the destination beginning with "FROM" or "TO".

Format the component_name as: FROM_{DESTINATION} or TO_{DESTINATION}
Replace spaces with underscores. Uppercase everything.
Example: "TO CLOSED DRAIN TANK V-005" → "TO_CLOSED_DRAIN_TANK_V-005"

- level: "out_of_system"
- component_name: the text beginning with FROM or TO, formatted as above
- confidence: high / medium / low

===========================
CONNECTIONS
===========================

Every line segment between two nodes is one connection.

Line types:
- major_process: thick solid lines — main process flow
- minor_process: thin solid lines — instrument taps, small connections
- signal: dashed lines — pneumatic, electrical, or hydraulic signals

Fields:
- line_type: major_process / minor_process / signal
- start_id: component_name of the start node
- end_id: component_name of the end node
- pipeline: a UUID you generate shared across all connection segments belonging to the
  same continuous physical pipe. Segments split by a valve or junction share the same
  pipeline UUID.
- metadata: any visible specs — pipe size, line number, insulation, flow direction,
  temperature rating. Infer meaning from context.
- confidence: high / medium / low

PIPE SEGMENTATION RULE:
If any component (valve, instrument, junction) sits in the middle of a pipe, record it
as two separate connection segments — one on each side of the component. Both segments
share the same pipeline UUID.

Example — valve MV-715-01 on pipe between FROM_SLUG_CATCHER_V-710 and F-715A:
  segment 1: start_id=FROM_SLUG_CATCHER_V-710, end_id=MV-715-01, pipeline=<shared-uuid>
  segment 2: start_id=MV-715-01, end_id=F-715A, pipeline=<shared-uuid>

===========================
OUTPUT FORMAT
===========================

Return ONLY valid JSON, no markdown, no preamble:
{
    "nodes": [
        {
            "level": "equipment",
            "component_name": "F-715A",
            "metadata": {
                "design_pressure_psig": 275,
                "operating_pressure_psig": 250,
                "design_temp_f": 100
            },
            "confidence": "high"
        },
        {
            "level": "instrument",
            "component_name": "PSV-715A",
            "metadata": {
                "set_point_psig": 275,
                "inlet_size": "3/4",
                "outlet_size": "1"
            },
            "confidence": "high"
        },
        {
            "level": "valve",
            "component_name": "MV-715-01",
            "metadata": {
                "nominal_pipe_size": "6'' D2R"
            },
            "confidence": "high"
        },
        {
            "level": "junction",
            "component_name": "j1",
            "metadata": {
                "description": "3-way split below turbine meter"
            },
            "confidence": "medium"
        },
        {
            "level": "out_of_system",
            "component_name": "TO_CLOSED_DRAIN_TANK_V-005",
            "metadata": {},
            "confidence": "high"
        }
    ],
    "connections": [
        {
            "line_type": "major_process",
            "start_id": "FROM_SLUG_CATCHER_V-710",
            "end_id": "MV-715-01",
            "pipeline": "shared-pipeline-uuid",
            "metadata": {
                "pipe_id": "6-PL-2000-D",
                "size_inches": 6
            },
            "confidence": "high"
        },
        {
            "line_type": "major_process",
            "start_id": "MV-715-01",
            "end_id": "F-715A",
            "pipeline": "shared-pipeline-uuid",
            "metadata": {
                "pipe_id": "6-PL-2000-D",
                "size_inches": 6
            },
            "confidence": "high"
        },
        {
            "line_type": "minor_process",
            "start_id": "j1",
            "end_id": "PSV-715A",
            "pipeline": "instrument-line-uuid",
            "metadata": {},
            "confidence": "high"
        }
    ],
    "uncertainties": "..."
}

===========================
UNCERTAINTIES
===========================

After extracting all connections, verify every node has at least one connection.
If a node has no connections, look again more carefully before marking it as isolated.

Add a top-level "uncertainties" field: a short (1-3 sentence) note on what you found
most confusing or uncertain on this page — e.g. ambiguous labels, overlapping/crossing
lines, illegible tags, or unclear connections. If nothing was unclear, say so briefly.
"""

PID_EXTRACTION_PROMPT_V3 = r"""
You are analyzing one segment of a larger P&ID diagram. This image is a
cropped region — components and pipes may be partially visible or exit the
frame. This is expected. Extract everything you can see in this segment,
even if partially visible. For pipes that exit the frame create an
out_of_system node in the direction they leave (e.g.
OUT_OF_FRAME_RIGHT, OUT_OF_FRAME_BOTTOM). Do not say you cannot see
the full diagram — extract what is visible.
""" + PID_EXTRACTION_PROMPT_V2


SEGMENT_PROMPT = r"""
You are analyzing ONE SEGMENT of a larger P&ID (Piping and Instrumentation Diagram)
for an oil and gas facility, extracting data to construct a digital twin via a graph.

This image is a cropped region of a full diagram. Components and pipes may be partially
visible or run off the edge of the segment — this is EXPECTED. Extract everything you can
see in this segment, even if partially visible. Do not apologize for or comment on seeing
only a fragment — just extract what is present.

=====================================================================
HOW THIS IMAGE IS COLORED — READ CAREFULLY
=====================================================================

This image has two visual layers you must treat differently:

1. BLACK AND WHITE layer — the original diagram.
   ALL component information is in black and white: equipment vessels, instrument circles,
   valve symbols, tag labels (e.g. "MV-715-01", "F-715A"), specifications, and text.
   When identifying NODES and reading their names/specs, use ONLY the black and white
   content. Colored overlays are NOT part of any component's identity.

2. COLOR layer — the pipe lines.
   The process pipes have been drawn over in unique colors. Each colored line carries a
   text label of the form "line_<number>" (e.g. "line_5", "line_12") repeated along its
   length. These colored lines and their "line_N" labels are the ONLY thing you use to
   record CONNECTIONS. A colored line's identity is its "line_N" label.

Do not confuse the two. A black-and-white tag like "MV-715-01" is a component name.
A colored "line_5" label is a pipe identifier. Never mix them.

=====================================================================
NODES  (identify from the BLACK AND WHITE layer only)
=====================================================================

Every node has these fields:
- level: equipment / instrument / valve / out_of_system
- component_name: each level has a specific pattern; each component name is unique
- metadata: dict of component specifications
- confidence: high / medium / low

NAMING CONVENTION:
Always use dashes as separators in component_name tags, never underscores.
Correct: PSV-715A, DPI-715A, PI-715A
Wrong:   PSV_715A, DPI_715A, PI_715A

IMPORTANT: Do NOT create junction nodes. Junctions are handled later by a separate
process. Only extract equipment, instrument, valve, and out_of_system nodes.

---

LEVEL 1 — EQUIPMENT
Equipment is always a large vessel, exchanger, pump, or cooler with an underlined title.
Each equipment component typically has two references on the full diagram. Both references
are in the largest text size and underlined. One reference sits next to the component
symbol. The other floats in an uncrowded area with specifications next to it. Record those
specifications by inferring meaning from context and store them in the metadata dict.
(In a segment, you may see only one of the two references — that is fine, but if you are seeing the segment which has the specs, record them. 

- level: "equipment"
- component_name: the underlined name (e.g. "F-715A", "V-745")
  regex: r'^[A-Z]+-\d+[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. design pressure,
  operating pressure, design temperature, size, capacity)
- confidence: high / medium / low

---

LEVEL 2 — INSTRUMENTS
Instruments are small circles connected to equipment or pipes by thin lines.
Inside each circle are 2-3 letters identifying the instrument type followed by a number.
Common types:
- PSV: Pressure Safety Valve — circle with spring/triangle actuator above
- PI: Pressure Indicator
- PDI: Pressure Differential Indicator
- LG: Level Gauge — typically two connection points on vessel side
- LT/PT/TT: Level/Pressure/Temperature Transmitter
- LAH/LAL: Level Alarm High/Low
- TC/TI: Temperature Controller/Indicator

- level: "instrument"
- component_name: letters followed by dash followed by numbers and optionally a letter
  (e.g. PSV-715A, DPI-715A, PI-715A)
  regex: r'^[A-Z]+-\d+[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. inlet size, outlet size,
  set pressure)
- confidence: high / medium / low

---

LEVEL 3 — VALVES
Valves sit directly on process lines, interrupting them with a symbol.
Common symbols:
- Bow-tie or X shape: manual gate/globe valve (tagged MV-xxx)
- Bow-tie with actuator on top: control valve
- Bow-tie with circle on stem: ball valve
- Arrow pointing into line: check valve

Extract ALL visible valve tags. Never skip — use low confidence if the label is hard to read.

- level: "valve"
- component_name: full tag (e.g. "MV-715-01", "MV-742-03")
  regex: r'^MV-\d{3}-\d{2,3}[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. nominal_pipe_size)
- confidence: high / medium / low

---

OUT OF SYSTEM
Used when a pipe leaves the page. These occur near the edges of the full diagram and have
text describing the destination beginning with "FROM" or "TO".

Format the component_name as: FROM_{DESTINATION} or TO_{DESTINATION}
Replace spaces with underscores. Uppercase everything.
Example: "TO CLOSED DRAIN TANK V-005" -> "TO_CLOSED_DRAIN_TANK_V-005"

- level: "out_of_system"
- component_name: the text beginning with FROM or TO, formatted as above
- confidence: high / medium / low

=====================================================================
CONNECTIONS  (record from the COLOR layer only)
=====================================================================

Each process pipe is drawn as a uniquely colored line labeled "line_<number>".
A pipe that passes through a component (valve, instrument) is split into separate colored
segments on each side of that component — so the color may change at a component. This is
expected and correct.

YOUR TASK FOR CONNECTIONS:
For EACH colored line visible in this segment, report:
  - color: the "line_N" label printed on that line (e.g. "line_5")
  - endpoints: the list of component_names (from the black-and-white layer) that this
    colored line visibly TOUCHES within this segment
  - line_type: major_process / minor_process / signal (infer from the underlying line)

CRITICAL RULES FOR endpoints:
- Report ONLY what the colored line touches IN THIS SEGMENT. Do not guess or infer where
  the line goes outside the visible crop.
- A colored line may touch 1 or 2 components in this segment:
    * 2 components — both ends terminate at a visible component here.
    * 1 component — the line touches one component and then exits the segment edge
      (the other end is in a different segment). Report the single component.
- If a colored line passes through the segment without touching any visible component,
  do NOT report it (it will be captured in the segments where it does touch something).
- If you can see a colored line clearly but CANNOT read its "line_N" label, still report
  it with "color": "unreadable" and list its endpoints, and note this in uncertainties.
- List EVERY distinct component the colored line meets. If one colored line touches three
  or more components, list them all — do NOT invent a junction; just list the components.

Line types:
- major_process: thick solid lines — main process flow
- minor_process: thin solid lines — instrument taps, small connections
- signal: dashed lines — pneumatic, electrical, or hydraulic signals

=====================================================================
OUTPUT FORMAT
=====================================================================

Return ONLY valid JSON, no markdown, no preamble:
{
    "nodes": [
        {
            "level": "equipment",
            "component_name": "F-715A",
            "metadata": {
                "design_pressure_psig": 275,
                "operating_pressure_psig": 230,
                "design_temp_f": 100
            },
            "confidence": "high"
        },
        {
            "level": "instrument",
            "component_name": "PSV-715A",
            "metadata": {
                "set_point_psig": 275,
                "inlet_size": "3/4",
                "outlet_size": "1"
            },
            "confidence": "high"
        },
        {
            "level": "valve",
            "component_name": "MV-715-01",
            "metadata": {
                "nominal_pipe_size": "6'' D2R"
            },
            "confidence": "high"
        },
        {
            "level": "out_of_system",
            "component_name": "TO_CLOSED_DRAIN_TANK_V-005",
            "metadata": {},
            "confidence": "high"
        }
    ],
    "connections": [
        {
            "color": "line_5",
            "endpoints": ["FROM_SLUG_CATCHER_V-710", "MV-715-01"],
            "line_type": "major_process",
            "confidence": "high"
        },
        {
            "color": "line_8",
            "endpoints": ["MV-715-01"],
            "line_type": "major_process",
            "confidence": "medium"
        }
    ],
    "uncertainties": "..."
}

=====================================================================
UNCERTAINTIES
=====================================================================

Add a top-level "uncertainties" field: a short (1-3 sentence) note on what you found most
confusing or uncertain in this segment — e.g. ambiguous labels, unreadable "line_N" color
labels, overlapping/crossing lines, illegible tags, or unclear connections. If nothing was
unclear, say so briefly.
"""

# ============================================================================
# PASS 1 — NODE EXTRACTION (uncolored segments, nodes only)
# ============================================================================

NODE_ONLY_PROMPT = r"""
You are analyzing ONE SEGMENT of a larger P&ID (Piping and Instrumentation Diagram)
for an oil and gas facility, extracting components to construct a digital twin.

This image is a cropped region of a full diagram. Components may be partially visible
or run off the edge of the segment — this is EXPECTED. Extract every component you can
see, even if partially visible. Do not comment on seeing only a fragment — just extract
what is present.

Extract NODES ONLY. Do not extract connections or pipes. Do not create junctions.

Every node has these fields:
- level: equipment / instrument / valve / out_of_system
- component_name: each level has a specific pattern; each component name is unique
- metadata: dict of component specifications
- confidence: high / medium / low

NAMING CONVENTION:
Always use dashes as separators in component_name tags, never underscores.
Correct: PSV-715A, DPI-715A, PI-715A
Wrong:   PSV_715A, DPI_715A, PI_715A

=====================================================================
TAG NUMBER OCR - CRITICAL 
=====================================================================
Component tag numbers contain only DIGITS (0-9), never letters, except for an
optional single trailing letter suffix (A or B).

You frequently misread the digit "0" as the letter "D" or "O". When you see a
"D" or "O" inside the numeric part of a tag, it is the digit "0".

Examples of the SAME tag read correctly:
  "MV-720-D4"  -> "MV-720-04"   (D is really 0)
  "MV-715-D2"  -> "MV-715-02"
  "V-OD5"      -> "V-005"       (O and D are both really 0)
  "V-73D"      -> "V-730"

The trailing suffix letter (A/B) is real and stays:
  "MV-715-02A" stays "MV-715-02A"
  "MV-715-15B" stays "MV-715-15B"

Read the structure as: LETTERS - DIGITS - DIGITS (optional trailing A/B).
Any "D" or "O" sitting among digits is the digit 0.


---

LEVEL 1 — EQUIPMENT
Equipment is always a large vessel, exchanger, pump, or cooler with an underlined title.
Each equipment component typically has two references on the full diagram. Both references
are in the largest text size and underlined. One reference sits next to the component
symbol. The other floats in an uncrowded area with specifications next to it. Record those
specifications by inferring meaning from context and store them in metadata.
(In a segment you may see only one of the two references — that is fine.)

- level: "equipment"
- component_name: the underlined name (e.g. "F-715A", "V-745")
  regex: r'^[A-Z]+-\d+[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. design_pressure_psig,
  operating_pressure_psig, design_temp_f, size, capacity)
- confidence: high / medium / low

---

LEVEL 2 — INSTRUMENTS
Instruments are small circles connected to equipment or pipes by thin lines.
Inside each circle are 2-3 letters identifying the instrument type followed by a number.
Common types:
- PSV: Pressure Safety Valve — circle with spring/triangle actuator above
- PI: Pressure Indicator
- PDI: Pressure Differential Indicator
- LG: Level Gauge — typically two connection points on vessel side
- LT/PT/TT: Level/Pressure/Temperature Transmitter
- LAH/LAL: Level Alarm High/Low
- TC/TI: Temperature Controller/Indicator

- level: "instrument"
- component_name: letters, dash, numbers, optional trailing letter (e.g. PSV-715A, PI-715A)
  regex: r'^[A-Z]+-\d+[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. set_pressure_psig,
  inlet_size, outlet_size)
- confidence: high / medium / low

---

LEVEL 3 — VALVES
Valves sit directly on process lines, interrupting them with a symbol.
Common symbols:
- Bow-tie or X shape: manual gate/globe valve (tagged MV-xxx)
- Bow-tie with actuator on top: control valve
- Bow-tie with circle on stem: ball valve
- Arrow pointing into line: check valve

Extract ALL visible valve tags. Never skip — use low confidence if the label is hard to read.

- level: "valve"
- component_name: full tag (e.g. "MV-715-01", "MV-742-03")
  regex: r'^MV-\d{3}-\d{2,3}[A-Z]?$'
- metadata: all visible specs — infer meaning from context (e.g. nominal_pipe_size)
- confidence: high / medium / low

---

OUT OF SYSTEM
Used when a pipe leaves the page. These occur near the edges of the full diagram and have
text describing the destination beginning with "FROM" or "TO".

Format the component_name as: FROM_{DESTINATION} or TO_{DESTINATION}
Replace spaces with underscores. Uppercase everything.
Example: "TO CLOSED DRAIN TANK V-005" -> "TO_CLOSED_DRAIN_TANK_V-005"

- level: "out_of_system"
- component_name: the text beginning with FROM or TO, formatted as above
- confidence: high / medium / low

===========================
OUTPUT FORMAT
===========================

Return ONLY valid JSON, no markdown, no preamble:
{
    "nodes": [
        {
            "level": "equipment",
            "component_name": "F-715A",
            "metadata": {
                "design_pressure_psig": 275,
                "operating_pressure_psig": 230,
                "design_temp_f": 100
            },
            "confidence": "high"
        },
        {
            "level": "valve",
            "component_name": "MV-715-01",
            "metadata": {"nominal_pipe_size": "6\"-D2R"},
            "confidence": "high"
        }
    ],
    "uncertainties": "..."
}

Add a top-level "uncertainties" field: 1-3 sentences on what was hard to read or ambiguous
in this segment. If nothing was unclear, say so briefly.
"""


# ============================================================================
# PASS 2 — CONNECTION EXTRACTION (full color-coded image + known node list)
# ============================================================================



CONNECTION_PROMPT = r"""
You are tracing the pipe CONNECTIONS in a full P&ID (Piping and Instrumentation
Diagram) for an oil and gas facility, to construct a digital twin graph.

This image has two visual layers — treat them differently:

1. BLACK AND WHITE layer — the original diagram: equipment vessels, instruments,
   valves, and their text tags. This is where the components are.

2. COLOR layer — the process pipes have been drawn over in colors. Each colored
   line carries a label of the form "line_<number>" (e.g. "line_5"). Color is a
   tracing aid only — see the rules below for exactly how to use it.

The components have ALREADY been identified. Here is the complete list of known
components — use these EXACT names, never invent new ones:

{node_list}

=====================================================================
HOW TO USE COLOR  (read carefully — this is subtle)
=====================================================================

Color helps you FOLLOW a pipe, but it is NOT a perfect signal:

- SAME color along a path = definitely the same continuous pipe. Follow it.
- Color MAY CHANGE at a corner/bend even though it is still ONE pipe continuing.
  A color change by itself does NOT mean a new pipe or a junction — it is often
  just the pipe turning a corner.
- A junction does NOT require a color change. A pipe can run straight through a
  junction keeping its color while another pipe taps into it.

THEREFORE: use color to keep track of which physical line you are following, but
determine CONNECTIONS and JUNCTIONS from the geometry of where lines actually
meet — NOT from where colors change.

=====================================================================
THE MOST IMPORTANT RULE — DO NOT GUESS BY PROXIMITY
=====================================================================

Do NOT connect a component to a nearby vessel just because it sits close to it.
Physical closeness is NOT a connection. Many valves sit right next to a vessel
but actually connect to ANOTHER valve or a junction on the other end of their
pipe.

A connection exists ONLY if you can follow a continuous pipe (one color, or one
color continuing around a corner) from one component to the other. If you cannot
trace an actual pipe between two things, do NOT report a connection between them.

Follow the pipe to its real endpoint. That endpoint is usually another valve,
an instrument, or a junction — and only sometimes the large vessel nearby.

=====================================================================
JUNCTIONS  (3-way tees only)
=====================================================================

A junction is a point where exactly THREE pipe ends meet — a tee. This happens
when a line branches into two, or when one line taps into another line's run.
Every junction has exactly 3 connections to it. There are NO 4-way junctions.

CROSSINGS ARE NOT JUNCTIONS: where two lines cross in an X, one line hops over
the other with a visible gap/break. They do NOT connect. Never create a junction
at a crossing. Only create a junction where 3 pipe ends genuinely meet with no
gap.

When you find a junction:
- Create a junction node named "j1", "j2", "j3", ... (assign sequentially)
- Report exactly 3 connections, each from the junction to one of the 3 pipe ends
  it joins (a component or another junction)

=====================================================================
LINE TYPES
=====================================================================
- major_process: thick solid lines — main process flow
- minor_process: thin solid lines — instrument taps, small connections
- signal:        dashed lines — pneumatic, electrical, or hydraulic signals


=====================================================================
TAG NUMBER OCR - CRITICAL 
=====================================================================
Component tag numbers contain only DIGITS (0-9), never letters, except for an
optional single trailing letter suffix (A or B).

You frequently misread the digit "0" as the letter "D" or "O". When you see a
"D" or "O" inside the numeric part of a tag, it is the digit "0".

Examples of the SAME tag read correctly:
  "MV-720-D4"  -> "MV-720-04"   (D is really 0)
  "MV-715-D2"  -> "MV-715-02"
  "V-OD5"      -> "V-005"       (O and D are both really 0)
  "V-73D"      -> "V-730"

The trailing suffix letter (A/B) is real and stays:
  "MV-715-02A" stays "MV-715-02A"
  "MV-715-15B" stays "MV-715-15B"

Read the structure as: LETTERS - DIGITS - DIGITS (optional trailing A/B).
Any "D" or "O" sitting among digits is the digit 0.

=====================================================================
SMALL VENT?DRAIN VALVES - CRITICAL 
=====================================================================

SMALL VENT/DRAIN VALVES: valves on small (1/2", 1") lines near a vessel
usually do NOT connect directly to the vessel. They chain to OTHER small
valves and instruments (PSV, PI) through junctions — a relief/drain manifold.
If you cannot trace a small valve's line, do NOT default to connecting it to
the nearest vessel. Leave it out and note it.

=====================================================================
PROCEDURE
=====================================================================
1. Pick a colored pipe. Follow it from one end to the other, continuing around
   corners even if the color changes, until you reach a component or a junction.
2. Record that connection using EXACT component names (or a junction node).
3. Where a third pipe end meets a line along its run, create a 3-way junction.
4. Repeat until every visible pipe is traced.
5. Do NOT add connections you cannot trace. Omit uncertain ones (note them in
   uncertainties) rather than guessing by proximity.

=====================================================================
OUTPUT FORMAT
=====================================================================

Return ONLY valid JSON, no markdown, no preamble:
{{
    "junctions": [
        {{"component_name": "j1", "confidence": "high"}}
    ],
    "connections": [
        {{
            "start_id": "FROM_SLUG_CATCHER_V-710",
            "end_id": "j1",
            "line_type": "major_process",
            "confidence": "high"
        }},
        {{
            "start_id": "j1",
            "end_id": "MV-715-02A",
            "line_type": "major_process",
            "confidence": "high"
        }},
        {{
            "start_id": "j1",
            "end_id": "MV-715-02B",
            "line_type": "major_process",
            "confidence": "high"
        }}
    ],
    "uncertainties": "..."
}}

Add a top-level "uncertainties" field: 1-3 sentences on connections you were
unsure about — crossings, dense manifolds, or ambiguous endpoints. If you were
tempted to guess a connection by proximity but could not trace it, say so here
instead of inventing the connection.
"""


EQUIPMENT_METADATA_PROMPT = r"""
You are reading the EQUIPMENT SPECIFICATIONS from a full P&ID (Piping and
Instrumentation Diagram) for an oil and gas facility.

The equipment vessels have ALREADY been identified. Here is the list of known
equipment — extract specs ONLY for these, using these EXACT names:

{equipment_list}

WHERE TO LOOK:
Each equipment item has an underlined header/title block listing its
specifications. These header blocks are almost always in the UPPER THIRD of the
page, floating in an open/uncrowded area away from the vessel symbol itself.
The header is large, underlined text. Look there first.

A header block has the equipment name(s) and tag, a description of the vessel
type, and a list of spec lines. The labels you will see include things like
SIZE, OPERATING, DESIGN, MDMT, and DESIGN CAP, each followed by values and
units (PSIG, °F, GPM, PSID, O.D., T/T, etc.). Read the actual values printed on
THIS diagram — do not assume any particular numbers.

A single header may cover several equipment items at once (for example a tag
written as "X-NNN A & B" applies to both X-NNNA and X-NNNB) — in that case give
the same specs to each named item.

WHAT TO EXTRACT (infer meaning + units from context):
- size: the physical size string exactly as printed (e.g. an O.D. and a
  tan-to-tan length with their units)
- operating_pressure_psig: operating pressure as a number
- design_specs: {{ pressure_psig, temp_f }}  (the DESIGN pressure and maximum
  design temperature)
- MDMT: {{ pressure_psig, temp_f }}  (Minimum Design Metal Temperature;
  temp_f is the temperature, which may be negative — keep the sign)
- design_cap: {{ gpm, psid_clean }}  (design capacity flow and clean pressure drop)

Use numbers (not strings) for all numeric values. Omit any field you genuinely
cannot find rather than guessing.

OCR NOTE: you sometimes misread the digit "0" as "D" or "O". In any numeric
spec, "D"/"O" among digits is the digit 0.

TEMPERATURE RANGES WRITTEN AS "X/Y": design temp and MDMT are often printed
together as a single MIN/MAX pair, e.g. "MWP 350 PSIG @ -20/400 F". This is
TWO separate numbers, not one:
  - the lower (often negative) number -> MDMT.temp_f
  - the higher number -> design_specs.temp_f
Example: "-20/400 F" means MDMT.temp_f = -20 and design_specs.temp_f = 400.
NEVER concatenate the two numbers into one value (e.g. "-20/400" is NOT 20400).

OUTPUT FORMAT — return ONLY valid JSON, no markdown, no preamble. The values
below are illustrative placeholders ONLY; report the actual values you read
from the diagram:
{{
    "equipment": {{
        "<equipment_name>": {{
            "size": "<size string as printed>",
            "operating_pressure_psig": 0,
            "design_specs": {{ "pressure_psig": 0, "temp_f": 0 }},
            "MDMT": {{ "pressure_psig": 0, "temp_f": 0 }},
            "design_cap": {{ "gpm": 0, "psid_clean": 0 }}
        }}
    }},
    "uncertainties": "..."
}}

Include an entry for every known equipment name. If a header is missing or
unreadable for an item, include the name with an empty object {{}} and note it
in uncertainties.
"""


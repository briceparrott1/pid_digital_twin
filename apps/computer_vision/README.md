interface-takehome/
├── docker-compose.yml
├── .env
├── .gitignore
├── README.md
├── test.py
│
└── apps/
    └── computer-vision/
        ├── Dockerfile
        ├── requirements.txt
        ├── main.py
        ├── pipeline.py
        │
        ├── data/
        │   ├── pid/
        │   │   └── diagram.pdf
        │   └── sop/
        │       └── sop.docx
        │
        ├── core/
        │   ├── __init__.py
        │   └── config.py
        │
        ├── models/
        │   ├── __init__.py
        │   ├── analyze.py
        │   ├── report.py
        │   └── graph.py
        │
        ├── parsers/
        │   ├── __init__.py
        │   ├── pdf_parser.py
        │   └── sop_parser.py
        │
        ├── extraction/
        │   ├── __init__.py
        │   ├── prompts.py
        │   └── extractor.py
        │
        ├── agent/
        │   ├── __init__.py
        │   ├── state.py
        │   ├── tools.py
        │   └── graph.py
        │
        ├── services/
        │   ├── __init__.py
        │   ├── extraction_service.py
        │   └── report_service.py
        │
        └── db/
            ├── __init__.py
            ├── neo4j_client.py
            ├── loader.py
            └── queries.py






 // 1. List all jobs and their status
  MATCH (j:Job) RETURN j.id, j.status, j.created_at ORDER BY j.created_at DESC

  // 2. Full graph for one job (components + connections)
  MATCH (j:Job {id: "<job_id>"})-[:CONTAINS]->(n)
  OPTIONAL MATCH (n)-[r:CONNECTED_TO]-(m)
  RETURN j, n, r, m

  // 3. Just the pipe network (connections + endpoints, incl. External stubs)
  MATCH (a)-[r:CONNECTED_TO {job_id: "<job_id>"}]->(b)
  RETURN a, r, b

  // 4. Component breakdown by label/level
  MATCH (j:Job {id: "<job_id>"})-[:CONTAINS]->(n)
  RETURN labels(n) AS labels, n.level AS level, count(*) AS count
  ORDER BY level

  // 5. SOP violations
  MATCH (n) WHERE n.sop_violation = true
  RETURN labels(n), n.id, n.violation

  Job 17a28d7b-f46b-4217-9ffe-e629df625eb3 is a completed run with 85 components you can plug into <job_id>.


:style
node.Job { caption: '{component_name}'; }
node.Equipment { caption: '{component_name}'; }
node.Instrument { caption: '{component_name}'; }
node.Valve { caption: '{component_name}'; }
node.Connector { caption: '{component_name}'; }
node.OffPageEndpoint { caption: '{component_name}'; }


MATCH (n) WHERE NOT n:Job
  OPTIONAL MATCH
  (n)-[r:CONNECTED_TO]-(m)
  RETURN n, r, m
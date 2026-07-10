"""Economic sentiment reports: per-state, national, and per-NAICS-sector.

Deterministic aggregation (aggregate, industry) feeds a template renderer
(render) and an optional LLM narrative written by the cluster's Ollama
service (ollama), with official BLS payroll context on the national and
sector payloads (bls); generate orchestrates the pipeline and file output.
"""

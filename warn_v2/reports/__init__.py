"""Economic sentiment reports: per-state, national, and per-NAICS-sector.

Deterministic aggregation (aggregate, industry) feeds a template renderer
(render), with official BLS payroll context on the national and sector
payloads (bls); generate orchestrates the pipeline and file output. The
written analysis comes from the /layoff-sentiment Claude Code skill, which
reads the exported payloads.json.
"""

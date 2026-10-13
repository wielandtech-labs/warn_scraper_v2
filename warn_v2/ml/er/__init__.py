"""Learned entity resolution for Company rows (see docs/ml/entity-resolution-model-card.md).

Pipeline: records (one profile per raw Company) -> blocking (candidate
pairs) -> features (no enrichment fields) -> labels (weak, from unique ids)
-> model (calibrated pairwise GBM) -> cluster (constrained average linkage)
-> evaluate (pairwise + B-cubed). Nothing here writes canonical_company_id;
the model only proposes merges for an admin to accept.
"""

MODEL = "entity_resolution"

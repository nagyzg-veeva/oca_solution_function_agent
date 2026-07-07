"""Tuning constants for the Builder-Critic merge logic.

Kept separate from config.config so importing these does not trigger the
.env validation / sys.exit side effects, and to avoid a circular import
between graph.py and validator.py.
"""

# Number of failed validations allowed before falling back to human review.
MAX_RETRIES = 3

# Component-group Jaccard threshold (symmetric overlap) at or above which a
# proposed function is considered a structural near-duplicate of an existing
# registry function. Auto-merge (with corroboration) and gray-zone (without)
# both gate on this. The overlap coefficient is logged as a diagnostic only
# and is never used for routing (prevents the containment trap).
CG_JACCARD_THRESHOLD = 0.8

# Name similarity threshold (rapidfuzz token_set_ratio, 0-100 scale) for the
# corroboration prong of auto-merge.
NAME_SIM_THRESHOLD = 80

# Primary-object Jaccard threshold for the corroboration prong of auto-merge.
OBJECT_OVERLAP_THRESHOLD = 0.75

"""Tuning constants for the Builder-Critic merge logic.

Kept separate from config.config so importing these does not trigger the
.env validation / sys.exit side effects, and to avoid a circular import
between graph.py and validator.py.
"""

# Number of failed validations allowed before falling back to human review.
MAX_RETRIES = 3

# How many nearest registry neighbours the validator retrieves per proposed
# function. >1 gives visibility into secondary overlaps (logged, not merged).
REGISTRY_SEARCH_K = 3

# Cosine-similarity score (higher = more similar) at or above which a proposed
# function is considered an overlap that must be merged into the existing one.
OVERLAP_THRESHOLD = 0.8

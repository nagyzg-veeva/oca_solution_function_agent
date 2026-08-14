"""Tuning constants for the Builder-Critic merge logic.

Kept separate from config.config so importing these does not trigger the
.env validation / sys.exit side effects, and to avoid a circular import
between graph.py and validator.py.
"""

# Number of failed validations allowed before falling back to human review.
MAX_RETRIES = 50

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

# Independent gray-zone triggers (do NOT require CG Jaccard). Two functions can
# be the same business capability yet be assembled from different/overlapping
# component-group sets across runs, so CG Jaccard alone misses them. These let a
# near-identical name OR a near-identical business description defer a pair to
# the LLM adjudicator (which reads full descriptions) even when CG overlap is
# low. Kept deliberately high so only strong semantic near-duplicates are
# deferred; the adjudicator is the precision filter, so a false defer only costs
# one LLM call, never a false merge.
#
# Name similarity (rapidfuzz token_set_ratio, 0-100 scale) at or above which a
# pair is deferred to the adjudicator regardless of component-group overlap.
# Lowered 90->85: the observed cross-run duplicates cluster at token_set_ratio
# 80-86 (e.g. "Case & Inquiry Management" vs "Medical Inquiry Management" = 83.7,
# "Case Lifecycle & Operations Management" vs "Case & Inquiry Management" = 81.0),
# just under the old gate, so they fell to NO_MERGE and were inserted as
# duplicates. The adjudicator is the precision filter, so a slightly-low bar only
# costs an LLM call, never a false merge.
NAME_GRAY_THRESHOLD = 85

# Business-description cosine similarity (GoogleGenerativeAI embeddings, higher =
# more similar) at or above which a pair is deferred to the adjudicator
# regardless of component-group overlap.
#
# Calibrated empirically against gemini-embedding-001, which compresses the
# similarity range (all pharma-CRM functions share domain vocabulary): true
# same-function duplicates score ~0.83-0.89, distinct-but-related functions
# ~0.68, and unrelated functions ~0.62. 0.80 sits in the wide empty band
# between the duplicate and non-duplicate clusters. Because the adjudicator is
# the precision filter, a slightly-low threshold only costs an LLM call, never a
# false merge — so we err toward the recall side of that gap.
DESC_COSINE_THRESHOLD = 0.80

# Independent primary-object-overlap gray-zone trigger, for granular functions.
# A self-contained function recurring across domains tends to have a SMALL
# component-group set and drifting itemized descriptions, so it can under-fire on
# cg_jaccard, name_sim, AND desc_cosine at once — yet it almost always operates
# on the same primary object(s). This trigger catches that case. It is gated by a
# SECONDARY (lower) cosine so it does not flood the adjudicator with genuinely
# distinct functions that merely share a common object (e.g. two unrelated
# Account functions): same objects alone is not enough; the descriptions must
# also be moderately similar. Both signals must clear their bar to defer.
#
# OBJECT_GRAY_THRESHOLD is a Jaccard over primary-object SETS, so 0.75 already
# demands near-identical object sets ([Account] vs [Account, Child] = 0.5, below
# the bar) — the trigger only fires for functions on essentially the same objects.
# DESC_COSINE_SECONDARY calibrated empirically against gemini-embedding-001:
# granular recurrences (same function reworded across domains) score ~0.82-0.86,
# while distinct functions sharing an object (e.g. two different Account
# functions) score ~0.69-0.73. 0.72 sits just below the recurrence cluster and
# above the distinct cluster; the adjudicator backstops any borderline defer.
OBJECT_GRAY_THRESHOLD = 0.75
DESC_COSINE_SECONDARY = 0.72

# Containment (overlap-coefficient) gray-zone trigger. The dominant observed
# duplicate shape is a SMALL function whose component groups are a near-subset of
# a LARGER function's — overlap_coeff ~1.0 but symmetric cg_jaccard low (e.g. a
# 1-CG "Event Management & Visual Summaries" fully inside a 9-CG "Event & Speaker
# Operations Management"). cg_jaccard is size-sensitive and misses this; the
# overlap coefficient (intersection / smaller set) catches it. Historically
# overlap_coeff was logged as a diagnostic only to avoid the "containment trap"
# (a granular function sharing one common CG with a big aggregate is not
# necessarily a duplicate). We now DO route on it, but only into the gray zone
# and only WITH a corroborating semantic signal (similar name OR moderately
# similar description), so the adjudicator — not the scorer — makes the final
# call. Naked containment (one shared CG, unrelated name/description) still
# routes NO_MERGE.
OVERLAP_GRAY_THRESHOLD = 0.8
# Name corroboration for the containment path (token_set_ratio, 0-100). Lower
# than NAME_GRAY_THRESHOLD because here it only corroborates strong structural
# containment rather than triggering a defer by itself.
NAME_CORROB_THRESHOLD = 80

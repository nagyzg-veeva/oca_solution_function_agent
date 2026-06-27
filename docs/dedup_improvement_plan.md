# Solution Function Duplicate Detection — Findings & Improvement Plan

> Status: Proposal (pre-implementation)
> Scope: Improve reliability of duplicate/overlap detection between generated Solution Functions.

## 1. How the current solution works

Duplicate detection lives entirely inside the **validator node** (rubric criterion 3, "Registry Overlap"):

1. `src/nodes/vault.py` (`write_to_vault_node`) writes each approved function to
   `solution_functions.csv` **and** calls `add_solution_function_to_store()`, which embeds the
   function's `business_description` into a module-level `InMemoryVectorStore` plus a parallel
   `registry` dict (`src/vector_store.py`).
2. `src/nodes/validator.py` (`_detect_overlaps`) takes each newly proposed function, embeds its
   `business_description`, runs `similarity_search_with_score`, and if the **top-1** neighbour
   scores `>= OVERLAP_THRESHOLD (0.75)` it emits a merge directive.
3. The synthesizer is then instructed to merge (adopt the existing id/name, union component groups).

So the **only** signal driving a merge decision is the **cosine similarity of the business-description
embedding**, gated by a **single global scalar threshold**, against the **single closest** neighbour.

## 2. Root cause analysis — confirmed against the data

Parsing the 9 DCR-related rows in `solution_functions.csv` exposes the problem:

| ID | Name | Component Groups |
|---|---|---|
| V_3864168D | Account Data Validation & DCR Management | `2014, 2043, 8042` |
| V_A23D0BDB | Data Change Request (DCR) & Validation | `2014, 2043, 8042` |
| V_2CDE37E7 | Data Change Request (DCR) & Validation | `2014, 2043, 8042` |
| V_D8C03CDA | Data Change Requests & Validation | `2014, 2043, 8042` |
| V_807E4971 | Data Change Request (DCR) & Validation | `2014, 2043, 8042` |
| V_159C5A83 | Data Change Requests & Validation | `2014, 2043, 8042` |
| V_9A9A14B9 | DCR & Validation Management | `2014, 2043, 8015, 8042` |
| V_0FA6C969 | DCR & Validation Request | `2014, 2043, 8015, 8042` |

**Six functions with byte-identical component-group sets, identical primary objects, and
near-identical names were never merged.** A trivial set-equality check catches these instantly,
yet the embedding gate missed all of them. Four root causes:

### Root cause #1 — The dedup index is ephemeral and is never hydrated from the CSV (primary)
`InMemoryVectorStore` and `registry` are created **empty** at import. Only `write_to_vault_node`
ever populates them, and **`main.py` never loads `solution_functions.csv` back into the store at
startup** (`add_solution_function_to_store` is called from exactly one place: the write node).
Therefore every `python main.py` run starts **blind**: a proposed function is only compared against
functions created earlier *in the same process run*. Anything persisted by a previous run is
invisible. This fully explains how six identical DCR functions accumulated across separate runs.
**No threshold tuning can fix this** — it is a state-persistence bug.

### Root cause #2 — A single global threshold cannot separate "duplicate" from "merely related"
Embeddings of domain-specific business prose cluster into a narrow high band. "DCR & Validation"
(true dup) and "Account Data Validation" (related-but-distinct) sit close together. One scalar
`0.75` knob is precisely why raising it drops obvious dups while lowering it merges unrelated
functions — the reported symptom.

### Root cause #3 — The decision ignores the two strongest, cheapest signals
The match is made on the `business_description` embedding only. The **component-group ID sets** (an
exact structural fingerprint) and the **name** are discarded. `_detect_overlaps` even *reads*
`existing_component_groups` into the match payload but never uses it for the decision.

### Root cause #4 — Greedy, top-1, single-pass, no transitivity
Only the single closest neighbour is merged; secondary overlaps are merely logged
("v1 merges only the top match"). A↔B and B↔C will not collapse into one cluster.

### Minor
Leftover debug code: the `#TESZT` DCR print at `src/nodes/validator.py:36-40` should be removed.

## 3. Improvement plan

Principle: keep the LLM for genuine judgment in ambiguous cases; stop relying on an opaque cosine
threshold as the sole gate. Lead with deterministic, free structural signals.

### Fix A — Hydrate the registry from the CSV at startup (do first)
- Add `hydrate_registry_from_csv()` to `src/vector_store.py`.
- Call it once in `main.py` before the domain loop.
- Without this, every run is blind across runs and no algorithm change matters. This alone collapses
  most cross-run duplication because the next run will finally *see* prior functions.

### Fix B — Replace the single-threshold check with a multi-signal scorer
For each (proposed, candidate) pair compute:
1. **Component-group overlap** (primary signal): track both Jaccard `|A∩B|/|A∪B|` and the overlap
   coefficient `|A∩B|/min(|A|,|B|)`. Exact, deterministic, free, language-independent.
2. **Name similarity**: normalized token-set ratio (e.g. `rapidfuzz`) or name embedding.
3. **Primary-object overlap**: Jaccard on the object sets.
4. **Description semantic similarity**: keep the existing cosine, but as *one input*, not the gate.

Decide in tiers:
- **Auto-merge (no LLM):** CG Jaccard ≥ 0.8 **AND** (name sim high OR object overlap high).
  The six identical-CG DCRs hit this trivially.
- **Gray zone (one strong signal only):** escalate to a small **LLM adjudicator**
  ("same business function? merge yes/no + which is canonical").
- **No merge** otherwise.

> ⚠️ Guardrail for the "80% identical" rule: containment ≠ duplicate. The 3-CG DCR set is a *subset*
> of the 19-CG "Address Management & Inheritance" function (overlap coefficient = 1.0), but it must
> not be swallowed into the giant address function. Gate auto-merge on **symmetric** overlap
> (Jaccard, not just overlap coefficient) and/or a size-ratio + name/object agreement check. Use the
> overlap coefficient only to *flag for LLM review*, never to auto-merge.

### Fix C — Cluster the whole batch instead of greedy top-1
Build a similarity graph over {proposed ∪ registry} and merge connected components (union-find),
picking a canonical survivor (richest description / most CGs / earliest id). Gives transitive dedup.

### Fix D — Externalize the new knobs into `config/constants.py`
`CG_JACCARD_THRESHOLD`, `CG_OVERLAP_COEFF_THRESHOLD`, `NAME_SIM_THRESHOLD`,
`OBJECT_OVERLAP_THRESHOLD`; keep the semantic threshold for the gray zone.

### Cleanup
Remove the `#TESZT` debug block in `_detect_overlaps`.

## 4. Feasibility notes
- All data for Fixes B/C is **already present at validation time**: proposed functions carry
  `component_groups`, `primary_objects`, and `name`, and the registry stores the same. The
  component-group and name checks need **no new data and no embedding calls** — pure, fast,
  deterministic Python that can short-circuit before the embedding search.
- New dependency only if using `rapidfuzz` for name similarity (optional; a stdlib `difflib`
  fallback works).

## 5. Suggested implementation order
1. **Fix A** — startup hydration (state bug; highest impact, smallest change).
2. **Fix B (deterministic part)** — CG + name + object overlap with auto-merge tier.
3. **Fix C** — batch clustering / transitive merge.
4. **LLM adjudicator** — gray-zone resolution.
5. **Fix D** + cleanup throughout.

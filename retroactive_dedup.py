"""One-off retroactive dedup pass over the persisted registry (solution_functions.csv).

The Builder-Critic graph only scores NEWLY proposed functions against the
registry; it never re-compares existing CSV rows to each other. So duplicate
clusters written under earlier (looser) thresholds stay frozen on disk. This
script closes that gap once:

  1. Hydrate the registry/vector store from the CSV.
  2. Score every unordered pair of existing functions with the SAME deterministic
     scorer the validator uses (CG Jaccard, overlap coefficient, name similarity,
     primary-object Jaccard) PLUS the description-cosine signal (embeddings).
  3. Send every non-NO_MERGE pair to the SAME LLM adjudicator the graph uses, so
     the merge/no-merge decision is made by the precision filter, not the scorer.
  4. Union confirmed duplicates into transitive clusters, pick a canonical
     survivor per cluster, merge the rest into it, and rewrite the CSV.

Safety:
  * Dry-run by default — prints the plan and mutates nothing. Pass --apply to write.
  * On --apply, the original CSV is copied to solution_functions.csv.bak first.

Run:  uv run retroactive_dedup.py            # dry run (report only)
      uv run retroactive_dedup.py --apply    # write changes (after backup)
"""
import argparse
import csv
import itertools
import shutil
import sys

# Importing config validates .env (GEMINI_API_KEY etc.) as a side effect, exactly
# as main.py relies on. Do it first so the LLM/embedding clients can authenticate.
import config.config  # noqa: F401

from src.dedup.scorer import score_pair, tier, Tier
from src.vector_store import registry, cosine_by_id
from src.nodes.vault import CSV_FILE, CSV_HEADER, hydrate_registry_from_csv, _dedup, _load_rows
from src.nodes.adjudicator import (
    structured_llm as adjudicator_llm,
    SYSTEM_PROMPT as ADJUDICATOR_PROMPT,
    _format_prompt,
    AdjudicationResult,
)


def _order_key(rec: dict):
    """Canonical-survivor ranking: the richest function wins.

    Larger component-group set first (it is the aggregate that structurally
    contains the smaller duplicate), then higher complexity, then id for a
    stable tie-break.
    """
    return (
        len(rec.get("component_groups", [])),
        rec.get("complexity_score", 0),
        rec.get("solution_function_id", ""),
    )


def _find_duplicate_pairs():
    """Score every unordered pair; adjudicate the non-NO_MERGE ones.

    Returns (confirmed_edges, considered) where confirmed_edges is a list of
    (loser_id, winner_id, rationale) and considered is the count of pairs sent
    to the LLM.
    """
    ids = list(registry.keys())
    # Precompute each function's description-cosine map against all others once.
    cosine_maps = {fid: cosine_by_id(registry[fid]["business_description"]) for fid in ids}

    confirmed = []
    considered = 0

    for a_id, b_id in itertools.combinations(ids, 2):
        a, b = registry[a_id], registry[b_id]
        # Symmetric cosine; take the max of the two directed lookups.
        dc = max(cosine_maps[a_id].get(b_id, 0.0), cosine_maps[b_id].get(a_id, 0.0))
        score = score_pair(a, b, desc_cosine=dc)
        t = tier(score)
        if t == Tier.NO_MERGE:
            continue

        # Canonical = richer function; the other is the merge candidate ("proposed").
        winner, loser = (a, b) if _order_key(a) >= _order_key(b) else (b, a)
        considered += 1

        auto = t == Tier.AUTO_MERGE
        prompt = _format_prompt(loser, [(winner, score)])
        try:
            result: AdjudicationResult = adjudicator_llm.invoke([
                {"role": "system", "content": ADJUDICATOR_PROMPT},
                {"role": "user", "content": prompt},
            ])
        except Exception as e:
            print(f"   [adjudicator] LLM failed for '{loser['name']}' vs "
                  f"'{winner['name']}': {e}; skipping (no merge).")
            continue

        tier_label = "AUTO" if auto else "GRAY"
        if result.merge:
            confirmed.append((loser["solution_function_id"], winner["solution_function_id"], result.rationale))
            print(f"   ✅ MERGE  [{tier_label}] '{loser['name']}' -> '{winner['name']}'  "
                  f"(cg_jac={score.cg_jaccard:.2f} ovl={score.overlap_coeff:.2f} "
                  f"name={score.name_sim:.0f} desc={score.desc_cosine:.2f}) :: {result.rationale}")
        else:
            print(f"   ❌ keep   [{tier_label}] '{loser['name']}' vs '{winner['name']}'  "
                  f":: {result.rationale}")

    return confirmed, considered


def _cluster(confirmed_edges):
    """Directed forest of absorptions -> {canonical_id: [absorbed_ids]}.

    Deliberately NOT undirected union-find. A small function can be confirmed as
    a subset of two DISTINCT larger functions (e.g. a 1-CG "FMV Calculation
    Launchers" fully inside both "Event Speaker & Qualification" and "FMV Rate
    Management"). Union-find would then fuse those two large, distinct functions
    together through their shared satellite — a merge the adjudicator never
    approved for that pair. Instead, each absorbed function points to exactly ONE
    canonical (its richest confirmed winner), and two canonicals are merged only
    when a confirmed edge names one of them as the loser directly. Subset chains
    (A->B->C) still collapse to their terminal canonical C.
    """
    # Each loser points to its single richest winner.
    parent = {}
    best_key = {}
    for loser, winner, _ in confirmed_edges:
        key = _order_key(registry[winner])
        if loser not in best_key or key > best_key[loser]:
            best_key[loser] = key
            parent[loser] = winner

    def root(x):
        seen = set()
        while x in parent and x not in seen:
            seen.add(x)
            x = parent[x]
        return x  # terminal canonical (never itself an absorbed loser)

    clusters = {}
    for loser in parent:
        clusters.setdefault(root(loser), set()).add(loser)
    return {canonical: sorted(members) for canonical, members in clusters.items()}


def _merge_records(canonical_id, absorbed_ids):
    """Build the merged canonical record: union CGs/objects, re-estimate complexity.

    Complexity is stored per-function (not per-CG) on disk, so a naive sum would
    double-count shared component groups. We estimate a per-CG rate for each
    function (complexity / #CGs) and, for every CG in the union, take the highest
    rate among the functions that contain it, then sum. This never double-counts
    a shared CG and uses the strongest available signal per CG.
    """
    members = [registry[canonical_id]] + [registry[i] for i in absorbed_ids]

    union_cgs = _dedup([c for m in members for c in m.get("component_groups", [])])
    union_objs = _dedup([o for m in members for o in m.get("primary_objects", [])])

    rates = {}
    for m in members:
        cgs = m.get("component_groups", [])
        if not cgs:
            continue
        rate = m.get("complexity_score", 0) / len(cgs)
        for c in cgs:
            rates[c] = max(rates.get(c, 0.0), rate)
    complexity = round(sum(rates.get(c, 0.0) for c in union_cgs))

    canon = registry[canonical_id]
    return [
        canonical_id,
        canon["name"],                 # keep canonical (richest) name + description
        canon["business_description"],
        ", ".join(union_objs),
        ", ".join(union_cgs),
        complexity,
    ]


def main():
    parser = argparse.ArgumentParser(description="Retroactive dedup of solution_functions.csv")
    parser.add_argument("--apply", action="store_true",
                        help="Write the merged CSV (backs up to .bak first). Default: dry run.")
    args = parser.parse_args()

    n = hydrate_registry_from_csv()
    if n == 0:
        print("No functions hydrated from CSV; nothing to dedup.")
        return
    print(f"Hydrated {n} functions. Scoring {n * (n - 1) // 2} pairs and adjudicating overlaps...\n")

    confirmed, considered = _find_duplicate_pairs()
    print(f"\nAdjudicated {considered} candidate pair(s); {len(confirmed)} confirmed as duplicates.")

    clusters = _cluster(confirmed)
    if not clusters:
        print("No duplicate clusters found. CSV is clean under the current scorer.")
        return

    absorbed_total = sum(len(v) for v in clusters.values())
    print(f"\n{'='*60}")
    print(f"MERGE PLAN: {len(clusters)} cluster(s), removing {absorbed_total} duplicate row(s) "
          f"({n} -> {n - absorbed_total} functions)")
    print(f"{'='*60}")
    for canonical_id, absorbed in clusters.items():
        canon = registry[canonical_id]
        print(f"\n▶ KEEP  {canonical_id}  '{canon['name']}'  "
              f"({len(canon.get('component_groups', []))} CGs, cx={canon.get('complexity_score', 0)})")
        for aid in absorbed:
            a = registry[aid]
            print(f"   └─ merge {aid}  '{a['name']}'  "
                  f"({len(a.get('component_groups', []))} CGs, cx={a.get('complexity_score', 0)})")

    if not args.apply:
        print("\n[DRY RUN] No files changed. Re-run with --apply to write.")
        return

    # --- apply: read-modify-write, preserving original row order minus absorbed ---
    rows, order = _load_rows(CSV_FILE)
    absorbed_ids = {aid for absorbed in clusters.values() for aid in absorbed}

    for canonical_id, absorbed in clusters.items():
        rows[canonical_id] = _merge_records(canonical_id, absorbed)
    new_order = [rid for rid in order if rid not in absorbed_ids]

    shutil.copyfile(CSV_FILE, CSV_FILE + ".bak")
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for rid in new_order:
            writer.writerow(rows[rid])

    print(f"\n✅ Wrote {len(new_order)} functions to {CSV_FILE} "
          f"(backup at {CSV_FILE}.bak).")


if __name__ == "__main__":
    sys.exit(main())

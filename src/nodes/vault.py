import uuid
import csv
import os
from typing import Dict, Any, List
from src.state.schema import DomainState
from src.vector_store import add_solution_function_to_store, get_function

CSV_FILE = "solution_functions.csv"
CSV_HEADER = ["ID", "Name", "Description", "Primary Objects", "ComponentGroups", "Complexity Score"]


def _dedup(seq: List[str]) -> List[str]:
    """Order-preserving de-duplication."""
    seen = set()
    out = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _load_rows(csv_file: str):
    """Read the CSV into an id-keyed dict plus an ordered list of ids.

    Enables read-modify-write: existing rows are preserved and a merge updates
    the matching row in place rather than appending a duplicate.
    """
    rows: Dict[str, list] = {}
    order: List[str] = []
    if os.path.isfile(csv_file):
        with open(csv_file, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for r in reader:
                if not r:
                    continue
                rows[r[0]] = r
                order.append(r[0])
    return rows, order


def hydrate_registry_from_csv(csv_file: str = CSV_FILE) -> int:
    """Load all rows from solution_functions.csv into the in-memory registry
    and vector store at startup. Returns the number of rows hydrated.

    Without this, every run is blind to functions persisted by previous runs,
    and the validator cannot detect cross-run duplicates. Idempotent:
    add_solution_function_to_store keys by id, so re-runs overwrite in place.
    """
    rows, _ = _load_rows(csv_file)
    count = 0
    for row_id, r in rows.items():
        if len(r) < 6:
            continue
        name, desc = r[1], r[2]
        if not desc.strip():
            continue
        objects = [s.strip() for s in r[3].split(",") if s.strip()]
        cgs = [s.strip() for s in r[4].split(",") if s.strip()]
        try:
            complexity = int(r[5])
        except (ValueError, IndexError):
            complexity = 0
        add_solution_function_to_store(
            function_id=row_id,
            name=name,
            business_description=desc,
            component_groups=cgs,
            primary_objects=objects,
            complexity_score=complexity,
        )
        count += 1
    return count


def write_to_vault_node(state: DomainState) -> Dict[str, Any]:
    """
    Upserts approved Solution Functions to the Vault mock (solution_functions.csv)
    and synchronizes the Vector Store Registry.

    - New function (no solution_function_id): INSERT a new row with a fresh id.
    - Merge (solution_function_id set and present in the registry): UPDATE the
      existing record in place — union the component groups and primary objects,
      re-aggregate complexity from the per-component-group complexities, and
      adopt the consolidated description.
    """
    proposed_functions = state.get("proposed_functions", [])
    candidate_domain = state.get("candidate_domain", [])

    # Per-component-group complexity, used to re-aggregate on merge without
    # double counting (orphan component groups can appear in multiple domains).
    cg_complexity = {cg["id"]: cg.get("complexity", 0) for cg in candidate_domain}

    print("\n" + "=" * 50)
    print("🚀 WRITING TO VAULT & UPDATING REGISTRY")
    print("=" * 50)

    rows, order = _load_rows(CSV_FILE)

    for func in proposed_functions:
        sf_id = func.get("solution_function_id", "")
        existing = get_function(sf_id) if sf_id else None

        if existing:
            # --- MERGE: update the existing record in place ---
            func_id = sf_id
            name = existing["name"]  # adopt the existing (canonical) name
            description = func.get("business_description", existing["business_description"])

            existing_cgs = existing.get("component_groups", [])
            merged_cgs = _dedup(list(existing_cgs) + list(func.get("component_groups", [])))
            merged_objects = _dedup(list(existing.get("primary_objects", [])) + list(func.get("primary_objects", [])))

            # Re-aggregate complexity: existing total + complexity of only the
            # newly added component groups (dedup avoids double-counting orphans).
            existing_cg_set = set(existing_cgs)
            added_cgs = [c for c in func.get("component_groups", []) if c not in existing_cg_set]
            complexity = existing.get("complexity_score", 0) + sum(cg_complexity.get(c, 0) for c in added_cgs)

            action = "MERGED"
        else:
            # --- INSERT: brand-new function ---
            func_id = f"V_{uuid.uuid4().hex[:8].upper()}"
            name = func.get("name", "")
            description = func.get("business_description", "")
            merged_cgs = _dedup(list(func.get("component_groups", [])))
            merged_objects = _dedup(list(func.get("primary_objects", [])))
            complexity = func.get("complexity_score", 0)
            action = "INSERTED"

        row = [func_id, name, description, ", ".join(merged_objects), ", ".join(merged_cgs), complexity]
        if func_id not in rows:
            order.append(func_id)
        rows[func_id] = row

        # Vault (mock) is the source of truth; refresh the registry/vector store
        # to match. Keyed by func_id, so a merge overwrites the existing entry.
        add_solution_function_to_store(
            function_id=func_id,
            name=name,
            business_description=description,
            component_groups=merged_cgs,
            primary_objects=merged_objects,
            complexity_score=complexity,
        )

        print(f"✅ [VAULT MOCK] {action}: '{name}' (ID: {func_id})")
        print(f"   -> Objects: {merged_objects}")
        print(f"   -> Components: {len(merged_cgs)} items")
        print(f"   -> Complexity: {complexity}")

    # Read-modify-write the whole file (append mode cannot update rows in place).
    try:
        with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)
            for rid in order:
                writer.writerow(rows[rid])
    except Exception as e:
        # The registry was already updated in-memory; flag the divergence.
        print(f"⚠️  [VAULT MOCK] Failed to persist CSV ({e}); registry may be ahead of disk.")

    print("=" * 50 + "\n")
    return {}

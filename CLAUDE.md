# CLAUDE.md / AGENTS.md

This file provides guidance to Claude Code, Antigravity, and other agentic assistants when working with code in this repository.

> `AGENTS.md` is a symlink to this file, so OpenCode and other agents read the same content. Design and planning docs are in `docs/`.

## What this is

A Python application using **LangGraph and LangChain** to orchestrate a **Builder-Critic graph with a Human-in-the-Loop (HITL) step and an LLM-based Adjudicator**. It connects to a Veeva Vault service, fetches Salesforce Component Groups, abstracts them into business-oriented **Solution Functions**, and persists results to a CSV-backed mock registry with an in-memory vector store for semantic overlap detection. LLM calls use Google Gemini (`gemini-3.1-pro-preview`; embeddings `models/gemini-embedding-001`).

## Setup and Execution

- **Dependency management:** uses `uv`; all dependencies are declared in `pyproject.toml`. Python `>=3.12`.
- **Run:** `uv run main.py` (or `python main.py` with the virtualenv active).
- **Environment variables:** importing `config/config.py` validates the `.env` file as a side effect and calls `sys.exit(1)` unless a `.env` exists at the project root with non-empty values for:
  - `VAULT_HOSTNAME`
  - `VAULT_USERNAME`
  - `VAULT_PASSWORD`
  - `VAULT_ORG_NAME`
  - `GEMINI_API_KEY`
- **Tests / lint / format:** none are configured in `pyproject.toml`.

## Architecture & Code Boundaries

Graph flow (`src/graph.py`):
`START → synthesize → validate → [conditional route_after_validate] → adjudicate | synthesize | hitl_review | write_to_vault → END`

The graph is compiled with a `MemorySaver` checkpointer so `interrupt()` can pause and resume execution.

- **Entrypoint — `main.py`:** the orchestrator. Hydrates the vector store/registry via `hydrate_registry_from_csv()` at startup. Calls `get_component_groups()` to fetch candidate domains (clusters of overlapping Component Groups), sorts them by total complexity descending, and invokes the graph **once per domain** with a per-domain `thread_id`. Streams node events, detects the HITL interrupt, and resumes via `Command(resume={"corrected_functions": ...})`.
- **Config & Tuning Constants:**
  - `config/config.py` loads and validates env vars (importing it triggers `.env` check side effects).
  - `config/constants.py` holds tuning constants to avoid circular imports and `.env` side effects:
    - `MAX_RETRIES = 3` — failed validations before falling back to human review.
    - `CG_JACCARD_THRESHOLD = 0.8` — Component-group Jaccard similarity threshold above which proposed functions are checked for near-duplication.
    - `NAME_SIM_THRESHOLD = 80` — Name similarity threshold (`rapidfuzz` token-set ratio) for auto-merging.
    - `OBJECT_OVERLAP_THRESHOLD = 0.75` — Primary-object Jaccard similarity threshold for auto-merging.
- **State graph — `src/graph.py`:** core LangGraph definition, routing (`route_validation` & `route_after_validate`), and compilation.
- **Graph state — `src/state/schema.py`:** defines `DomainState` and `SolutionFunction` TypedDicts.
  - `candidate_domain`: Input list of `ComponentGroup` dicts.
  - `proposed_functions`: List of `SolutionFunction` dicts.
  - `validation_feedback`: LLM feedback on criteria 1 & 2.
  - `is_valid`: Boolean flag for the router.
  - `registry_matches`: List of exact merge directives passed to the Synthesizer.
  - `gray_zone_pairs`: Deferred candidate pairs for the Adjudicator.
  - `retry_count`: Accumulated retries using `operator.add` reducer.
- **Deterministic Scorer — `src/dedup/scorer.py`:**
  - Computes `ScoreBreakdown` (Component-group Jaccard, overlap coefficient, name similarity, primary-object Jaccard, and exact set equality).
  - Classifies candidate pairs into `AUTO_MERGE` (directly merged), `GRAY_ZONE` (deferred to the Adjudicator), or `NO_MERGE`.
- **Nodes — `src/nodes/`:**
  - `synthesizer.py` — **Builder.** Gemini (`gemini-3.1-pro-preview`, temp 0.2) proposing Solution Functions. Handles "Required Merges" by adopting existing IDs and names, and consolidating descriptions and component groups.
  - `validator.py` — **Critic.** Hybrid code + LLM (Gemini temp 0.1): Registry overlap (Criterion 3) is deterministic via the vector store/registry scorer (`_detect_overlaps`); No-Orphans (1) and Business Intent/Granularity (2) are LLM-judged. Promotes ambiguous multi-matches to the gray-zone.
  - `adjudicator.py` — **Adjudicator.** Resolves gray-zone pairs via Gemini temp 0.0 with structured output. If a merge is approved, it emits a merge directive and increments `retry_count` to force a synthesizer re-run.
  - `hitl.py` — calls LangGraph `interrupt()` when `retry_count >= MAX_RETRIES`; resumed externally via `Command(resume=...)`.
  - `vault.py` — `write_to_vault_node` upserts approved functions to `solution_functions.csv` (a local CSV mock) and syncs the in-memory vector store. Also contains `hydrate_registry_from_csv()` to populate the store at startup.
- **External connections — `src/tools/`:**
  - `vault_connector.py` — `VaultConnector` wraps the Veeva Vault REST API.
  - `vault_tools.py` — `get_component_groups()` queries Vault and clusters Component Groups by overlapping objects (graph DFS).
- **Vector store — `src/vector_store.py`:** `InMemoryVectorStore` + `GoogleGenerativeAIEmbeddings` as the in-memory registry of approved Solution Functions. A parallel `registry` dict is the source of truth for full records.

## Key invariants & gotchas

- **Registry overlap loop terminator:** a proposed function already carrying the `solution_function_id` of its closest registry match is treated as already-resolved and is NOT re-flagged — this prevents infinite overlap-merge loops.
- **Retry counter** must stay consistent with the `operator.add` reducer: emit `1` only on failure, omit on success; `main.py` initializes it to `0`.
- **Vault mock & Persistence:** `write_to_vault` persists to `solution_functions.csv`, which is hydrated back into memory at startup, solving cross-run duplicate blindness.
- **HITL:** the graph is compiled with `MemorySaver`; on `MAX_RETRIES` failures it routes to `hitl_review` and uses `interrupt()` to pause until human resolution resumes it.

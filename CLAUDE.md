# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> `AGENTS.md` is a symlink to this file, so OpenCode and other agents read the same content. Design and planning docs are in `docs/`.

## What this is

A Python application using **LangGraph and LangChain** to orchestrate a **Builder-Critic graph with a Human-in-the-Loop (HITL) step**. It connects to a Veeva Vault service, fetches Salesforce Component Groups, abstracts them into business-oriented **Solution Functions**, and persists results to a CSV-backed mock registry with an in-memory vector store for semantic overlap detection. LLM calls use Google Gemini (`gemini-3.1-pro-preview`; embeddings `models/gemini-embedding-001`).

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

Graph flow (`src/graph.py`): `START → synthesize → validate → [conditional] → synthesize | hitl_review | write_to_vault → END`. Compiled with a `MemorySaver` checkpointer so `interrupt()` can pause/resume.

- **Entrypoint — `main.py`:** the orchestrator. Calls `get_component_groups()` to fetch candidate domains (clusters of overlapping Component Groups), sorts them by total complexity descending, and invokes the graph **once per domain** with a per-domain `thread_id`. Streams node events, detects the HITL interrupt, and resumes via `Command(resume={"corrected_functions": ...})`.
- **Config:** `config/config.py` loads and validates env vars (importing it triggers the `.env` check as a side effect). `config/constants.py` holds tuning constants — kept separate to avoid circular imports and the `.env` side effect:
  - `MAX_RETRIES = 3` — failed validations before falling back to human review.
  - `REGISTRY_SEARCH_K = 3` — nearest registry neighbours retrieved per proposed function (>1 surfaces secondary overlaps, logged not merged).
  - `OVERLAP_THRESHOLD = 0.75` — cosine similarity at/above which a proposed function must be merged into the existing one.
- **State graph — `src/graph.py`:** core LangGraph definition, routing (`route_validation`), and compilation.
- **Graph state — `src/state/schema.py`:** `DomainState` and `SolutionFunction` TypedDicts. `retry_count` uses an `operator.add` reducer — the validator returns `1` on failure (accumulates) and omits the key on success. `solution_function_id` is `""` for a brand-new function or an existing registry id when the function is a merge into it.
- **Nodes — `src/nodes/`:**
  - `synthesizer.py` — **Builder.** Gemini (`gemini-3.1-pro-preview`, temp 0.2) with structured output (`SolutionFunctionModel`) proposes functions from a candidate domain; honors "Required Merges" from the validator.
  - `validator.py` — **Critic.** Hybrid code+LLM (Gemini temp 0.1): registry overlap (criterion 3) is deterministic via the vector store (`_detect_overlaps`); No-Orphans (1) and Business Intent/Granularity (2) are LLM-judged. Final validity requires LLM approval **AND** no unresolved overlaps.
  - `hitl.py` — calls LangGraph `interrupt()` when `retry_count >= MAX_RETRIES`; resumed externally via `Command(resume=...)`.
  - `vault.py` — `write_to_vault_node` upserts approved functions to `solution_functions.csv` (a **local CSV mock of Vault, not the live API**) and syncs the in-memory vector store. Handles INSERT (new) and MERGE (update in place) with dedup of component groups/objects and re-aggregated complexity.
- **External connections — `src/tools/`:**
  - `vault_connector.py` — `VaultConnector` wraps the Veeva Vault REST API (auth, VQL query, insert/update; basic auth + OAuth).
  - `vault_tools.py` — `get_component_groups()` queries Vault and clusters Component Groups by overlapping objects (graph DFS). Defines the `ComponentGroup` TypedDict.
- **Vector store — `src/vector_store.py`:** `InMemoryVectorStore` + `GoogleGenerativeAIEmbeddings` as the in-memory registry of approved Solution Functions. A parallel `registry` dict is the source of truth for full records (the vector store lacks a clean get-by-id). Used by the validator for semantic overlap detection.

## Key invariants & gotchas

- **Registry overlap loop terminator:** a proposed function already carrying the `solution_function_id` of its closest registry match is treated as already-resolved and is NOT re-flagged — this prevents infinite overlap-merge loops.
- **Retry counter** must stay consistent with the `operator.add` reducer: emit `1` only on failure, omit on success; `main.py` initializes it to `0`.
- **Vault mock:** `write_to_vault` persists to `solution_functions.csv`, not the live Vault API. The in-memory vector store registry is the source of truth during a run.
- **HITL:** the graph is compiled with `MemorySaver`; on `MAX_RETRIES` failures it routes to `hitl_review` and uses `interrupt()` to pause until human resolution resumes it.

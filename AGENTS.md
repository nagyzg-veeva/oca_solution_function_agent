# OpenCode Instructions (AGENTS.md)

This project is a Python application using LangGraph and LangChain to orchestrate a Builder-Critic graph with a Human-in-the-Loop (HITL) step. It connects to a Vault service and uses Google Gemini models.

## Setup and Execution

- **Dependency Management:** The project uses `uv`. All python dependencies are defined in `pyproject.toml`.
- **Running the App:** The main entrypoint is `main.py`. Execute it with `uv run main.py` or `python main.py` (if the virtual environment is active).
- **Environment Variables:** The application will fail to start (`sys.exit(1)`) unless a `.env` file exists at the project root with the following non-empty variables:
  - `VAULT_HOSTNAME`
  - `VAULT_USERNAME`
  - `VAULT_PASSWORD`
  - `GEMINI_API_KEY`

## Architecture & Code Boundaries

- **Entrypoint:** `main.py` is the orchestrator that fetches candidate domains from Vault and invokes the graph.
- **State Graph:** The core LangGraph definition, routing, and compilation is located in `src/graph.py`.
- **Graph State:** The state schemas used to pass data between nodes are in `src/state/schema.py`.
- **Nodes:** The functional steps of the graph (Synthesizer, Validator, HITL, Vault) are located in `src/nodes/`.
- **External Connections:** Vault API wrappers and LangChain tools for Vault are in `src/tools/`.

## Framework Quirks & Workflow Notes

- **Human in the Loop (HITL):** The graph is compiled with a `MemorySaver` checkpointer. When validation fails multiple times, the graph conditionally routes to the `hitl_review` node and uses LangGraph's `interrupt()` to pause execution and wait for human resolution before resuming.
- **Testing & Linting:** There are currently no test suites, linters, or formatters explicitly configured in `pyproject.toml`.

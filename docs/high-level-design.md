# Architecture Plan: Veeva CRM As-Is Solution Function Generator

## 1. Objective & Scope
*   **Goal:** Automatically abstract technical Salesforce Component Groups into business-oriented Solution Functions to aid migration to Vault CRM.
*   **Boundary:** Strictly an "As-Is" assessment tool. Mapping to "To-Be" Vault CRM capabilities is out of scope.

## 2. Data Ingestion & Pre-processing (The Clusterer)
*   **Source of Truth:** Veeva Vault (`oca_component_group__c`).
*   **Fetch:** A Python loader uses the Vault Connector to bulk-fetch all Component Groups for a given assessment.
*   **Clustering (Context Management):** Python logic builds an in-memory graph of the components and their data object dependencies. It groups them into cohesive **"Candidate Domains"** based on *Relational Proximity* (shared data objects) and *Semantic Similarity*.
*   **Sequencing:** Candidate Domains are sorted by **Descending Complexity/Centrality** (processing core pillars like `Account` or `Call2_vod__c` domains first to establish the architectural foundation).

## 3. State Management & Consistency
*   **Global Registry:** An **in-memory Vector Store** (e.g., FAISS/ChromaDB) is initialized at runtime. It stores the embeddings of all approved Solution Functions.
*   **Synchronization:** As functions are approved, they are written to Vault and simultaneously added to the vector store to maintain cross-run consistency without Vault API latency.

## 4. LangGraph Topology (Builder-Critic)
For each Candidate Domain, the graph executes the following loop:
*   **Synthesizer Agent (Builder - High-Tier LLM, e.g., GPT-4o / Claude 3.5 Sonnet):**
    *   Analyzes the Candidate Domain.
    *   Proposes Solution Functions including: Name, Business Description, Primary Objects, Component Groups, and Complexity Score.
*   **Validator Agent (Critic - High-Tier LLM, e.g., GPT-4o / Claude 3.5 Sonnet):**
    *   Critiques the proposal against a strict **Tripartite Rubric**:
        1.  *No Orphans:* All input Component Groups must be assigned.
        2.  *Business Intent:* Descriptions must focus on business outcomes, strictly no technical jargon (Apex, Trigger, etc.).
        3.  *Registry Overlap:* Queries the Vector Store. Rejects if semantic similarity to an existing function is >80%, forcing a merge.
*   **Auxiliary Tasks (Mid/Low-Tier LLM, e.g., GPT-4o-mini / Claude 3 Haiku):** Used for schema validation, formatting, or simple complexity calculations.

## 5. Edge Case Handling (HITL)
*   **Max Retries:** If the Synthesizer and Validator disagree and loop **3 times**, the graph aborts the loop for that domain.
*   **Fallback:** The domain is flagged as `Needs Human Review`. The LLM execution moves on to the next domain.

## 6. Output & Observability
*   **Target:** Veeva Vault (`oca_solution_function__c`).
*   **Schema:** 
    *   `solution_function_id`
    *   `name`
    *   `business_description`
    *   `primary_objects` (List)
    *   `component_groups` (List)
    *   `complexity_score`
*   **Audit Trail:** The `Reasoning_Log__c` field on the Vault record will capture:
    *   *Approved Functions:* A summary of the Synthesizer's justification.
    *   *HITL Flags:* The full transcript of the Synthesizer/Validator disagreement to aid the human architect in resolving it.

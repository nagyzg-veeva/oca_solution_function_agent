from typing import Optional
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document

# Initialize embedding model and in-memory vector store
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
vector_store = InMemoryVectorStore(embeddings)

# Authoritative registry of approved Solution Functions, keyed by
# solution_function_id. The vector store handles similarity search; this dict
# is the source of truth for the full record (component groups, complexity,
# etc.) that merges need to read back. InMemoryVectorStore has no clean
# get-by-id, so we keep the structured data here alongside it.
registry: dict[str, dict] = {}


def search_similar_functions(description: str, k: int = 1):
    """
    Search for semantically similar Solution Functions in the registry.
    Returns the top k matching documents as (Document, score) tuples. Each
    Document's metadata carries the full record (solution_function_id, name,
    component_groups, primary_objects, complexity_score), and page_content is
    the business description. The score is cosine similarity (higher = more
    similar), per langchain_core's InMemoryVectorStore.
    """
    results = vector_store.similarity_search_with_score(description, k=k)
    return results


def cosine_by_id(description: str) -> dict[str, float]:
    """
    Return a {solution_function_id: cosine_similarity} map of the given
    description against every function currently in the registry.

    Used by the validator's overlap detector as an independent, CG-agnostic
    signal: two functions describing the same business capability have highly
    similar descriptions even when assembled from different component groups.
    The score is cosine similarity (higher = more similar); an empty registry
    yields an empty map.
    """
    if not registry:
        return {}
    results = vector_store.similarity_search_with_score(description, k=len(registry))
    scores: dict[str, float] = {}
    for doc, score in results:
        fid = doc.metadata.get("solution_function_id") or doc.id
        if fid is not None:
            scores[fid] = float(score)
    return scores


def add_solution_function_to_store(
    function_id: str,
    name: str,
    business_description: str,
    component_groups: Optional[list] = None,
    primary_objects: Optional[list] = None,
    complexity_score: int = 0,
):
    """
    Add or update an approved Solution Function in the registry.

    We embed the business_description for similarity search and store the full
    record in both the vector store metadata and the `registry` dict. Passing
    `ids=[function_id]` makes a re-add overwrite the existing slot in place, so
    a merge refreshes the embedding and metadata instead of creating a
    duplicate document.
    """
    component_groups = component_groups or []
    primary_objects = primary_objects or []

    record = {
        "solution_function_id": function_id,
        "name": name,
        "business_description": business_description,
        "component_groups": component_groups,
        "primary_objects": primary_objects,
        "complexity_score": complexity_score,
    }

    doc = Document(
        page_content=business_description,
        metadata=dict(record),
    )
    # ids=[function_id] keys the document by the function id; re-adding the
    # same id overwrites it (the store is a dict keyed by id).
    vector_store.add_documents([doc], ids=[function_id])

    # Keep the authoritative registry in sync.
    registry[function_id] = record


def get_function(function_id: str) -> Optional[dict]:
    """
    Return the full stored record for a Solution Function by id, or None if it
    is not in the registry. Used by the write node to union component groups
    and re-aggregate complexity when merging.
    """
    return registry.get(function_id)

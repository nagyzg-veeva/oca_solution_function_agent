from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document

# Initialize embedding model and in-memory vector store
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
vector_store = InMemoryVectorStore(embeddings)

def search_similar_functions(description: str, k: int = 1):
    """
    Search for semantically similar Solution Functions in the registry.
    Returns the top k matching documents.
    """
    results = vector_store.similarity_search_with_score(description, k=k)
    return results

def add_solution_function_to_store(function_id: str, name: str, business_description: str):
    """
    Add an approved Solution Function to the local vector store.
    We embed the business_description.
    """
    doc = Document(
        page_content=business_description,
        metadata={"solution_function_id": function_id, "name": name}
    )
    vector_store.add_documents([doc])

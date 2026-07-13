import os
from functools import lru_cache
from langchain_core.prompts import PromptTemplate

PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))

@lru_cache(maxsize=16)
def get_prompt_template(name: str) -> PromptTemplate:
    """
    Loads a prompt template from a markdown file in the prompts directory,
    caches it, and returns a LangChain PromptTemplate.
    """
    file_path = os.path.join(PROMPTS_DIR, f"{name}.md")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Prompt file not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        template_text = f.read().strip()
    
    # We use template_format="f-string" as default, with no input variables for these system prompts
    return PromptTemplate(
        template=template_text,
        input_variables=[],
        template_format="f-string"
    )

def get_system_prompt(name: str) -> str:
    """
    Convenience helper to retrieve the raw string content of the prompt.
    """
    return get_prompt_template(name).template

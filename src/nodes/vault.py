import uuid
import csv
import os
from typing import Dict, Any
from src.state.schema import DomainState
from src.vector_store import add_solution_function_to_store

def write_to_vault_node(state: DomainState) -> Dict[str, Any]:
    """
    Simulates writing approved Solution Functions to Veeva Vault (oca_solution_function__c).
    Synchronizes the approved functions to the local Vector Store Registry.
    """
    proposed_functions = state.get("proposed_functions", [])
    
    print("\n" + "="*50)
    print("🚀 WRITING TO VAULT & UPDATING REGISTRY")
    print("="*50)
    
    csv_file = "solution_functions.csv"
    file_exists = os.path.isfile(csv_file)
    
    with open(csv_file, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["ID", "Name", "Business Description", "Primary Objects", "Component Groups", "Complexity Score"])
            
        for func in proposed_functions:
            func_id = f"V_{uuid.uuid4().hex[:8].upper()}"
            
            writer.writerow([
                func_id,
                func.get("name", ""),
                func.get("business_description", ""),
                ", ".join(func.get("primary_objects", [])),
                ", ".join(func.get("component_groups", [])),
                func.get("complexity_score", 0)
            ])
            
            # 1. Mock Write to Vault
            print(f"✅ [VAULT MOCK] Inserted: '{func['name']}' (ID: {func_id})")
            print(f"   -> Objects: {func['primary_objects']}")
            print(f"   -> Components: {len(func['component_groups'])} items")
            print(f"   -> Complexity: {func['complexity_score']}")
            
            # 2. Add to Local Vector Store Registry
            add_solution_function_to_store(
                function_id=func_id,
                name=func["name"],
                business_description=func["business_description"]
            )
        
    print("="*50 + "\n")
    return {}

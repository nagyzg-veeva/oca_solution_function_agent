import os
from dotenv import load_dotenv

# Load environment variables before any other imports that might need them
load_dotenv()

import pprint
import config.config as config
from src.tools.vault_tools import get_component_groups
from src.graph import app
from langgraph.types import Command

def main():
    print("Hello from oca!")
    print(f"Connecting to Vault: {config.VAULT_HOSTNAME}")

    print("Fetching Component Groups from Vault...")
    result = get_component_groups()
    candidate_domains = result.get("component_groups", [])
    
    # Sort candidate domains by total complexity descending
    def get_domain_complexity(domain):
        return sum(cg.get("complexity", 0) for cg in domain)
        
    candidate_domains.sort(key=get_domain_complexity, reverse=True)
    
    print(f"Discovered {len(candidate_domains)} Candidate Domains. Sorted by complexity.")
    
    # For testing purposes, limit to the first 2 candidate domains
    candidate_domains = candidate_domains[:2]
    
    for i, domain in enumerate(candidate_domains):
        print(f"\n{'='*60}")
        print(f"--- Processing Candidate Domain {i+1} ({len(domain)} component groups) ---")
        print(f"{'='*60}")
        
        thread_id = f"domain_thread_{i+1}"
        config_dict = {"configurable": {"thread_id": thread_id}}
        
        initial_state = {
            "candidate_domain": domain,
            "retry_count": 0,
            "validation_feedback": "",
            "is_valid": False,
            "proposed_functions": []
        }
        
        # Invoke the graph
        try:
            print("Invoking Builder-Critic Graph...")
            
            # Using stream to show progress through nodes
            for event in app.stream(initial_state, config_dict):
                for node_name, node_state in event.items():
                    print(f"[{node_name}] -> Processing...")
                    if node_name == "validate":
                        if node_state.get("is_valid"):
                            print("   ✅ Validation Passed!")
                        else:
                            print("   ❌ Validation Failed. Retrying...")
                            
            # To get the final state after streaming or pausing
            current_state = app.get_state(config_dict)
            
            # Check if there are pending tasks (which means it was interrupted)
            if len(current_state.next) > 0 and current_state.next[0] == "hitl_review":
                # Or if it's paused AT the hitl_review node due to interrupt()
                print("\n⚠️  GRAPH INTERRUPTED: Max retries exceeded.")
                print("   Awaiting human intervention.")
                
                # Fetch the interrupt payload from the state tasks
                # The interrupt payload is stored in the task's interrupts tuple
                if current_state.tasks:
                    task = current_state.tasks[0]
                    if task.interrupts:
                        interrupt_payload = task.interrupts[0].value
                        print(f"   Reason: {interrupt_payload.get('reason')}")
                        
                # Provide a mock resolution for demonstration purposes
                print("   [HUMAN] Resolving conflict manually and resuming...")
                
                # We resume with the last proposed functions (just as an example)
                last_proposal = current_state.values.get("proposed_functions", [])
                app.invoke(Command(resume={"corrected_functions": last_proposal}), config_dict)
                print("   ▶️  Graph Resumed.")
            else:
                print(f"Finished processing Domain {i+1}.")
            
        except Exception as e:
            print(f"Error during graph execution: {e}")
        
if __name__ == "__main__":
    main()

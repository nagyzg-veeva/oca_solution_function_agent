import os
from dotenv import load_dotenv
from src.tools.vault_connector import VaultConnector

load_dotenv()

VAULT_HOSTNAME = os.getenv("VAULT_HOSTNAME")
USERNAME = os.getenv("VAULT_USERNAME")
PASSWORD = os.getenv("VAULT_PASSWORD")
ORG_NAME = os.getenv("VAULT_ORG_NAME")


vc= VaultConnector(hostname=VAULT_HOSTNAME)
vc.login(username=USERNAME, password=PASSWORD)

query_comp_group = f"SELECT id, solution_function__c FROM oca_component_group__c WHERE org__cr.name__v='{ORG_NAME}'"
result = vc.query(query_comp_group)
print(result)

cgs_to_update = []
for record in result.get('data'):
    cgs_to_update.append({
        'id':record.get('id'),
        'solution_function__c':None
    })

update_result = vc.update(object='oca_component_group__c', data=cgs_to_update)
print(update_result)
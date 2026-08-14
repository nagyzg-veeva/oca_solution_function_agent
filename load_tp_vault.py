import os
import markdown
from dotenv import load_dotenv
import pandas as pd
from src.tools.vault_connector import VaultConnector


load_dotenv()

INPUT_FILENAME = "solution_functions.csv"
VAULT_HOSTNAME = os.getenv("VAULT_HOSTNAME")
USERNAME = os.getenv("VAULT_USERNAME")
PASSWORD = os.getenv("VAULT_PASSWORD")
ORG_NAME = os.getenv("VAULT_ORG_NAME")

SF = "oca_solution_function__c"
CG = "oca_component_group__c"


vc = VaultConnector(hostname=VAULT_HOSTNAME)
vc.login(username=USERNAME, password=PASSWORD)

df = pd.read_csv(INPUT_FILENAME)
print(df.head())

for row in df.itertuples():

    sf_to_insert = {
        "name__v": row.Name,
        "description__c": markdown.markdown(row.Description),
        "org__cr.name__v": ORG_NAME,
        "assessment_status_sf__c": "ready_for_review__c"
    }

    result = vc.insert(object=SF, data=[sf_to_insert])
    
    if result.get('responseStatus') == "SUCCESS" and result.get("data")[0].get('responseStatus') == "SUCCESS":
        sf_id = result.get("data")[0].get('data').get('id')


        cgs_to_update = []
        cg_ids = row.ComponentGroups
        for cg_id in cg_ids.split(', '):
            cgs_to_update.append({
                "id":cg_id,
                "solution_function__c": sf_id
            })

        if len(cgs_to_update) > 0:
            vc.update(object=CG, data=cgs_to_update)

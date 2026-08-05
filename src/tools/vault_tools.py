import csv
import os
import pprint
from typing import Annotated
from typing_extensions import TypedDict, IntVar

from src.tools.vault_connector import VaultConnector
import config.config as config


class Component(TypedDict):
    name: str
    component_type: str


class ComponentGroup(TypedDict):
    name: str
    id: str
    description: str
    objects: list[str]
    complexity: int


class ComponentGroups(TypedDict):
    component_groups: list[list[ComponentGroup]]


vc: VaultConnector = None


def get_vault_connector() -> VaultConnector:
    global vc
    if vc is None:
        vc = VaultConnector(hostname=config.VAULT_HOSTNAME)
        login_result = vc.login(username=config.VAULT_USERNAME, password=config.VAULT_PASSWORD)
        if login_result is False:
            print("Vault Login Error")
    return vc


def _group_component_groups(
    component_groups_list: list[ComponentGroup],
    orphaned_component_groups_list: list[ComponentGroup],
) -> ComponentGroups:
    """Group component groups into connected candidate domains by overlapping objects using DFS."""
    n = len(component_groups_list)
    adj = [[] for _ in range(n)]

    for i in range(n):
        set_i = set(component_groups_list[i]["objects"])
        if not set_i:
            continue
        for j in range(i + 1, n):
            set_j = set(component_groups_list[j]["objects"])
            if set_i.intersection(set_j):
                adj[i].append(j)
                adj[j].append(i)

    visited = [False] * n
    grouped_component_groups = []

    for i in range(n):
        if not visited[i]:
            current_group = []
            stack = [i]
            visited[i] = True

            while stack:
                node = stack.pop()
                current_group.append(component_groups_list[node])

                for neighbor in adj[node]:
                    if not visited[neighbor]:
                        visited[neighbor] = True
                        stack.append(neighbor)

            grouped_component_groups.append(current_group)

    if not grouped_component_groups and orphaned_component_groups_list:
        grouped_component_groups = [[]]

    for idx in range(len(grouped_component_groups)):
        grouped_component_groups[idx].extend(orphaned_component_groups_list)

    return {"component_groups": grouped_component_groups}


def get_component_groups() -> ComponentGroups:
    vc = get_vault_connector()

    query_component_groups = f"""SELECT id, name__v, total_cognitive_complexity__c, supplementary_information_ai__c, (SELECT object_api_name__c FROM component_group_object_joins__cr) FROM oca_component_group__c WHERE org_name__c='{config.VAULT_ORG_NAME}'"""
    result = vc.query(query_component_groups)

    if result.get("responseStatus") != "SUCCESS":
        return {"component_groups": []}

    component_groups_list = []
    orphaned_component_groups_list = []

    for item in result.get("data", []):
        subquery_data = item.get("component_group_object_joins__cr", {}).get("data", [])

        object_names = list({
            sub_item.get("object_api_name__c")
            for sub_item in subquery_data
            if sub_item.get("object_api_name__c") is not None
        })

        cg: ComponentGroup = {
            "id": item.get("id", ""),
            "name": item.get("name__v", ""),
            "description": item.get("supplementary_information_ai__c", ""),
            "complexity": int(item.get("total_cognitive_complexity__c", 0)),
            "objects": object_names,
        }

        if len(object_names) == 0:
            orphaned_component_groups_list.append(cg)
        else:
            component_groups_list.append(cg)

    return _group_component_groups(component_groups_list, orphaned_component_groups_list)


def load_component_groups_from_csv(csv_path: str = "component_groups.csv") -> ComponentGroups:
    """Load Component Groups from a local CSV file and construct Candidate Domains."""
    if not os.path.isfile(csv_path):
        print(f"⚠️  [CSV LOADER] File '{csv_path}' not found.")
        return {"component_groups": []}

    component_groups_list = []
    orphaned_component_groups_list = []

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not any(row.values()):
                continue

            cg_id = row.get("ID", "").strip()
            name = row.get("Name", "").strip()
            description = row.get("Description", "").strip()

            try:
                complexity = int(row.get("Complexity", 0))
            except (ValueError, TypeError):
                complexity = 0

            raw_objects = row.get("Objects", "")
            objects = [obj.strip() for obj in raw_objects.split(",") if obj.strip()]

            cg: ComponentGroup = {
                "id": cg_id,
                "name": name,
                "description": description,
                "complexity": complexity,
                "objects": objects,
            }

            if len(objects) == 0:
                orphaned_component_groups_list.append(cg)
            else:
                component_groups_list.append(cg)

    print(f"📄 [CSV LOADER] Loaded {len(component_groups_list) + len(orphaned_component_groups_list)} Component Groups from '{csv_path}'.")
    return _group_component_groups(component_groups_list, orphaned_component_groups_list)

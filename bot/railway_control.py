"""Admin-only Railway setup switcher. Token is injected as a Railway secret."""
from __future__ import annotations
import os
import requests

URL = "https://backboard.railway.com/graphql/v2"


def setup_toggle_available() -> bool:
    return all(os.getenv(k) for k in ("RAILWAY_CONTROL_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID"))


def set_env_flag(key: str, enabled: bool) -> bool:
    if not setup_toggle_available():
        return False
    headers = {"Authorization": "Bearer " + os.environ["RAILWAY_CONTROL_TOKEN"], "Content-Type": "application/json"}
    query = "mutation($i: VariableCollectionUpsertInput!){variableCollectionUpsert(input:$i)}"
    variables = {"i": {
        "projectId": os.environ["RAILWAY_PROJECT_ID"],
        "environmentId": os.environ["RAILWAY_ENVIRONMENT_ID"],
        "serviceId": os.environ["RAILWAY_SERVICE_ID"],
        "variables": {key: "true" if enabled else "false"},
    }}
    try:
        response = requests.post(URL, headers=headers, json={"query": query, "variables": variables}, timeout=20)
        return bool(response.ok and response.json().get("data", {}).get("variableCollectionUpsert"))
    except Exception:
        return False

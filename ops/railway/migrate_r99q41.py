#!/usr/bin/env python3
"""R99q41 — one-shot Railway migration to the NEW account (idempotent).

The old workspace was limited («We limited this workspace after detecting
unusual activity») and its service is down. This script rebuilds the service
on the new account from the API only — no clicking:

    RAILWAY_API_TOKEN=... python ops/railway/migrate_r99q41.py --dry-run
    RAILWAY_API_TOKEN=... python ops/railway/migrate_r99q41.py --apply \
        --repo vahidlesani/smc-scanner2 --branch release

What it does (each step skipped if it already exists):
  1. project  "viva-signals"   (+ environment "production")
  2. service  "smc-scanner2"   (NO source yet → no accidental first deploy)
  3. variables from `ops/railway/env_r99q41.json` (git-ignored; secrets live
     only on the operator's machine)
  4. instance policy: ON_FAILURE ×10, 1 replica, healthcheck /health,
     auto-deploy from git OFF (every deploy is an explicit dispatch)
  5. serviceConnect(repo, branch) → the ONE build, then deploy — only with
     `--deploy`.

Rate-limit discipline (his 10-21 instruction): one deploy per RELEASE, never
per commit. `release` is a squashed single-commit branch; `main` keeps the
history.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://backboard.railway.com/graphql/v2"
PROJECT_NAME = "viva-signals"
SERVICE_NAME = "smc-scanner2"
ENV_NAME = "production"
STATE_PATH = "/tmp/rail_migration_state.json"


def gql(token: str, query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json",
                 # Railway's edge rejects the default urllib agent with 403.
                 "User-Agent": "viva-ops/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode(errors="replace")[:800]}


def ok(resp: dict, what: str) -> dict:
    if resp.get("errors") or resp.get("http"):
        raise SystemExit(f"{what} FAILED: {json.dumps(resp, ensure_ascii=False)[:600]}")
    return resp.get("data") or {}


def find_project(token: str) -> dict | None:
    d = ok(gql(token, "{ projects { edges { node { id name } } } }"), "list projects")
    for e in (d.get("projects") or {}).get("edges", []):
        if (e["node"].get("name") or "") == PROJECT_NAME:
            return e["node"]
    return None


def find_service(token: str, project_id: str) -> dict | None:
    q = ('query($id:String!){project(id:$id){services{edges{node{id name '
         'serviceInstances{edges{node{id environmentId}}}}}}}}')
    d = ok(gql(token, q, {"id": project_id}), "list services")
    for e in (((d.get("project") or {}).get("services") or {}).get("edges") or []):
        if e["node"].get("name") == SERVICE_NAME:
            return e["node"]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--deploy", action="store_true", help="connect the repo and build")
    ap.add_argument("--repo", default="vahidlesani/smc-scanner2")
    ap.add_argument("--branch", default="release")
    ap.add_argument("--env-file", default=os.path.join(os.path.dirname(__file__), "env_r99q41.json"))
    args = ap.parse_args()
    token = os.environ.get("RAILWAY_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("RAILWAY_API_TOKEN is required")
    print("token:", token[:8] + "…" + token[-4:], "| apply:", args.apply, "| deploy:", args.deploy)

    state: dict = {}
    if os.path.exists(STATE_PATH):
        state = json.load(open(STATE_PATH))

    # 1 ── project + environment
    proj = find_project(token)
    if proj is None:
        print("project: creating", PROJECT_NAME)
        if args.apply:
            d = ok(gql(token,
                       'mutation($i:ProjectCreateInput!){projectCreate(input:$i){'
                       'id name environments{edges{node{id name}}}}}',
                       {"i": {"name": PROJECT_NAME, "defaultEnvironmentName": ENV_NAME,
                              "description": "Viva Signals Pro (migrated 2026-10-21)"}}),
                   "projectCreate")
            proj = d["projectCreate"]
        else:
            print("   (dry-run) would create")
            return
    env_id = None
    for e in (proj.get("environments") or {}).get("edges", []):
        if e["node"]["name"] == ENV_NAME:
            env_id = e["node"]["id"]
    if not env_id:
        q = 'query($id:String!){project(id:$id){environments{edges{node{id name}}}}}'
        d = ok(gql(token, q, {"id": proj["id"]}), "environments")
        for e in d["project"]["environments"]["edges"]:
            if e["node"]["name"] == ENV_NAME:
                env_id = e["node"]["id"]
    print("project:", proj["id"], "| environment:", env_id)

    # 2 ── service (no source yet → nothing builds)
    svc = find_service(token, proj["id"])
    if svc is None:
        print("service: creating", SERVICE_NAME)
        d = ok(gql(token,
                   'mutation($i:ServiceCreateInput!){serviceCreate(input:$i){id name}}',
                   {"i": {"projectId": proj["id"], "name": SERVICE_NAME}}),
               "serviceCreate")
        svc = d["serviceCreate"]
    svc_id = svc["id"]
    print("service:", svc_id)

    # 3 ── variables
    if os.path.exists(args.env_file):
        variables = json.load(open(args.env_file))
        print("variables:", len(variables), "from", args.env_file)
        if args.apply:
            ok(gql(token,
                   'mutation($i:VariableCollectionUpsertInput!){variableCollectionUpsert(input:$i)}',
                   {"i": {"projectId": proj["id"], "environmentId": env_id,
                          "serviceId": svc_id, "replace": False,
                          "skipDeploys": True, "variables": variables}}),
               "variables")
    else:
        print("variables: NO env file at", args.env_file, "— skipped")

    # 4 ── instance policy: cheap, single replica, no git auto-deploy
    if args.apply:
        ok(gql(token,
               'mutation($e:String!,$s:String!,$i:ServiceInstanceUpdateInput!){'
               'serviceInstanceUpdate(environmentId:$e,serviceId:$s,input:$i)}',
               {"e": env_id, "s": svc_id,
                "i": {"restartPolicyType": "ON_FAILURE", "restartPolicyMaxRetries": 10,
                      "numReplicas": 1, "healthcheckPath": "/health",
                      "healthcheckTimeout": 120}}),
           "serviceInstanceUpdate")
        print("instance policy: ON_FAILURE×10 · 1 replica · /health")
        try:
            ok(gql(token,
                   'mutation($i:ServiceInstanceAutoDeployUpdateInput!){'
                   'serviceInstanceAutoDeployUpdate(input:$i)}',
                   {"i": {"projectId": proj["id"], "environmentId": env_id,
                          "serviceId": svc_id, "enabled": False}}),
               "autoDeploy")
            print("auto-deploy on push: OFF (one deploy per release)")
        except SystemExit as exc:
            print("auto-deploy update skipped:", str(exc)[:200])

    # 5 ── the single build
    if args.deploy:
        print("connecting source:", args.repo, "@", args.branch)
        ok(gql(token,
               'mutation($id:String!,$i:ServiceConnectInput!){serviceConnect(id:$id,input:$i){id}}',
               {"id": svc_id, "i": {"repo": args.repo, "branch": args.branch}}),
           "serviceConnect")
        ok(gql(token,
               'mutation($e:String!,$s:String!){serviceInstanceDeploy(environmentId:$e,serviceId:$s)}',
               {"e": env_id, "s": svc_id}),
           "serviceInstanceDeploy")
        print("deploy: requested")

    state.update({"projectId": proj["id"], "environmentId": env_id, "serviceId": svc_id})
    json.dump(state, open(STATE_PATH, "w"), indent=1)
    print("state →", STATE_PATH)
    print("github repo variables to set: RAILWAY_PROJECT_ID=%s RAILWAY_ENVIRONMENT_ID=%s "
          "RAILWAY_SERVICE_ID=%s" % (proj["id"], env_id, svc_id))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Railway read-only inspector (R62-ARENA ops) — prints NO secret values.

Runs inside GitHub Actions (the Arena sandbox has no route to Railway) or on
any machine with network access. Auth, in priority order:
  RAILWAY_TOKEN      project token  → header  Project-Access-Token
  RAILWAY_API_TOKEN  account/team   → header  Authorization: Bearer

Usage:
  python ops/railway/rw_api.py access     # project, env, services, deploys, volumes
  python ops/railway/rw_api.py usage      # CPU / RAM / network per service, 7 days
  python ops/railway/rw_api.py ids        # prints PROJECT_ID ENV_ID (for scripts)
Access is fail-closed: missing IDs, metadata, or GraphQL errors fail the probe.
Access never requests start commands or variable values. Safe GitHub annotations
make the result available even when log archive downloads are unavailable.
The usage report retains its existing best-effort behavior.
"""
import datetime as _dt
import json
import os
import re
import sys
import uuid
import urllib.request

API = "https://backboard.railway.com/graphql/v2"


# R63-ACCESS / Arena 01a0f47e: access-only logging, not trading logic.
def _redact_secrets(value):
    text = str(value)
    secrets = set()
    for name in ("RAILWAY_TOKEN", "RAILWAY_API_TOKEN", "BACKUP_PASSPHRASE"):
        raw = os.getenv(name, "")
        if raw:
            secrets.add(raw)
        if raw.strip():
            secrets.add(raw.strip())
    if secrets:
        pattern = "|".join(re.escape(s) for s in sorted(secrets, key=len, reverse=True))
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def _workflow_annotation(level, message):
    if level not in ("notice", "error"):
        raise ValueError("unsupported annotation level")
    if os.getenv("GITHUB_ACTIONS", "").lower() != "true":
        return
    safe = _redact_secrets(message)
    # GitHub workflow-command escaping; provider text cannot inject commands.
    safe = safe.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level} title=Railway access::{safe}")


def _public_id(value):
    # Only canonical UUID metadata is published, not arbitrary environment text.
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return "unavailable"


def _headers():
    h = {"Content-Type": "application/json", "User-Agent": "viva-ops/1.0"}
    pt = os.getenv("RAILWAY_TOKEN", "").strip()
    at = os.getenv("RAILWAY_API_TOKEN", "").strip()
    if pt:
        h["Project-Access-Token"] = pt
    elif at:
        h["Authorization"] = f"Bearer {at}"
    else:
        sys.exit("no RAILWAY_TOKEN / RAILWAY_API_TOKEN in env")
    return h


def gql(query, variables=None, account=False):
    h = _headers()
    if account:
        at = os.getenv("RAILWAY_API_TOKEN", "").strip()
        if not at:
            return None, ["(skipped: RAILWAY_API_TOKEN not set)"]
        h.pop("Project-Access-Token", None)
        h["Authorization"] = f"Bearer {at}"
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            out = json.loads(r.read().decode())
    except Exception as exc:  # network / HTTP
        return None, [f"HTTP: {type(exc).__name__}: {str(exc)[:200]}"]
    errs = [str(e.get("message", e))[:300] for e in (out.get("errors") or [])]
    return out.get("data"), errs


def ids():
    if os.getenv("RAILWAY_PROJECT_ID") and os.getenv("RAILWAY_ENVIRONMENT_ID"):
        return os.environ["RAILWAY_PROJECT_ID"], os.environ["RAILWAY_ENVIRONMENT_ID"]
    d, e = gql("query { projectToken { projectId environmentId } }")
    if d and d.get("projectToken"):
        return d["projectToken"]["projectId"], d["projectToken"]["environmentId"]
    message = "projectToken lookup failed: " + _redact_secrets(e)
    print(message)
    _workflow_annotation("error", message)
    return None, None


def _edges(x):
    return [n.get("node") for n in ((x or {}).get("edges") or [])]


def access():
    pid, eid = ids()
    print(_redact_secrets(f"project_id={pid}\nenvironment_id={eid}"))
    if not pid or not eid:
        _workflow_annotation("error", "Access failed: project and environment IDs are required.")
        return 1
    q = """query($id:String!){ project(id:$id){ name createdAt
          environments{ edges{ node{ id name } } }
          services{ edges{ node{ id name
              serviceInstances{ edges{ node{ environmentId numReplicas region
                  sleepApplication cronSchedule
                  latestDeployment{ id status createdAt } } } } } } }
          volumes{ edges{ node{ name
              volumeInstances{ edges{ node{ mountPath currentSizeMB sizeMB environmentId
                  serviceInstance{ serviceName } } } } } } } } }"""
    d, errors = gql(q, {"id": pid})
    for message in errors:
        print("  gql:", _redact_secrets(message))
    project = (d or {}).get("project") or {}
    if errors or not project:
        reason = "; ".join(errors) if errors else "project metadata was not returned"
        _workflow_annotation("error", "Access failed: " + reason)
        return 1
    envs = {n["id"]: n["name"] for n in _edges(project.get("environments"))}
    if eid not in envs:
        _workflow_annotation("error", "Access failed: selected environment was not returned by the project.")
        return 1
    print(_redact_secrets(f"\n== project: {project.get('name')}  (created {project.get('createdAt')})"))
    print(_redact_secrets("environments: " + ", ".join(
        f"{name}" + (" *" if ident == eid else "") for ident, name in envs.items())))
    print("\n== services")
    visible_services = set()
    for service in _edges(project.get("services")):
        for instance in _edges(service.get("serviceInstances")):
            if instance.get("environmentId") != eid:
                continue
            visible_services.add(service["id"])
            deployment = instance.get("latestDeployment") or {}
            print(_redact_secrets(
                f"- {service['name']}  id={service['id']}  replicas={instance.get('numReplicas')} "
                f"region={instance.get('region')} sleep={instance.get('sleepApplication')} "
                f"cron={instance.get('cronSchedule')}\n"
                f"    last deploy: {deployment.get('status')} @ {deployment.get('createdAt')}"))
    print("\n== volumes")
    visible_volumes = 0
    for volume in _edges(project.get("volumes")):
        for instance in _edges(volume.get("volumeInstances")):
            if instance.get("environmentId") != eid:
                continue
            visible_volumes += 1
            print(_redact_secrets(
                f"- {volume['name']}: {instance.get('mountPath')}  "
                f"{instance.get('currentSizeMB')}/{instance.get('sizeMB')} MB "
                f"svc={(instance.get('serviceInstance') or {}).get('serviceName')}"))
    result = json.dumps({
        "status": "verified",
        "project_id": _public_id(pid),
        "environment_id": _public_id(eid),
        "services": len(visible_services),
        "volumes": visible_volumes,
    }, sort_keys=True)
    _workflow_annotation("notice", result)
    return 0


def usage(days=7):
    pid, eid = ids()
    if not pid:
        return 1
    start = (_dt.datetime.utcnow() - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = """query($p:String!,$e:String!,$s:DateTime!){
        metrics(projectId:$p, environmentId:$e, startDate:$s, sampleRateSeconds:3600,
                groupBy:[SERVICE_ID],
                measurements:[CPU_USAGE, MEMORY_USAGE_GB, NETWORK_TX_GB, NETWORK_RX_GB, DISK_USAGE_GB]){
          measurement tags{ serviceId } values{ ts value } } }"""
    d, e = gql(q, {"p": pid, "e": eid, "s": start})
    for m in e:
        print("  gql:", m)
    names = {}
    d2, _ = gql("query($id:String!){ project(id:$id){ services{ edges{ node{ id name } } } } }", {"id": pid})
    for s in _edges(((d2 or {}).get("project") or {}).get("services")):
        names[s["id"]] = s["name"]
    print(f"== usage last {days}d (hourly samples)")
    rows = {}
    for r in (d or {}).get("metrics") or []:
        sid = ((r.get("tags") or {}).get("serviceId")) or "?"
        vals = [float(v.get("value") or 0) for v in (r.get("values") or [])]
        if not vals:
            continue
        rows.setdefault(names.get(sid, sid), {})[r["measurement"]] = (
            sum(vals) / len(vals), max(vals), vals[-1], len(vals))
    for svc, ms in rows.items():
        print(f"- {svc}")
        for m, (avg, mx, last, n) in sorted(ms.items()):
            print(f"    {m:16s} avg={avg:.3f} max={mx:.3f} last={last:.3f} (n={n})")
    # per-day CPU/RAM trend (the «مصرف چند روز اخیر بالا رفته» question)
    print("\n== daily trend (avg per day)")
    for r in (d or {}).get("metrics") or []:
        if r["measurement"] not in ("CPU_USAGE", "MEMORY_USAGE_GB"):
            continue
        sid = ((r.get("tags") or {}).get("serviceId")) or "?"
        by_day = {}
        for v in r.get("values") or []:
            day = _dt.datetime.utcfromtimestamp(int(v["ts"])).strftime("%m-%d")
            by_day.setdefault(day, []).append(float(v.get("value") or 0))
        line = " ".join(f"{k}:{sum(x)/len(x):.2f}" for k, x in sorted(by_day.items()))
        print(f"- {names.get(sid, sid)} {r['measurement']}: {line}")
    return 0


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["access"])[0]
    if cmd == "ids":
        p, e = ids()
        print(p or "", e or "")
        sys.exit(0 if p else 1)
    sys.exit({"access": access, "usage": usage}.get(cmd, access)())

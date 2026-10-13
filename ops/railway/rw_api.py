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
Every GraphQL error is printed (message only) and never aborts the report,
so a schema drift shows up in the log instead of hiding the rest.
"""
import datetime as _dt
import json
import os
import sys
import urllib.request

API = "https://backboard.railway.com/graphql/v2"


_MODE = None


def _probe(query, hdr):
    h = {"Content-Type": "application/json", "User-Agent": "viva-ops/1.0"}
    h.update(hdr)
    req = urllib.request.Request(API, data=json.dumps({"query": query}).encode(),
                                 headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _detect_mode():
    """Viva 10-14 («چی شد چرا انجام نمیشه»): the API secret may actually
    hold a PROJECT token (the dashboard hands people whichever string they
    copy). Probe BOTH header modes plus account mode and use the one that
    answers — no human round-trip, no secret value ever printed."""
    global _MODE
    if _MODE:
        return _MODE
    pt = os.getenv("RAILWAY_TOKEN", "").strip()
    at = os.getenv("RAILWAY_API_TOKEN", "").strip()
    if pt:
        _MODE = "project"
        return _MODE
    if not at:
        sys.exit("no RAILWAY_TOKEN / RAILWAY_API_TOKEN in env")
    probe = "query { projectToken { projectId } }"
    for mode, hdr in (("bearer", {"Authorization": f"Bearer {at}"}),
                      ("project", {"Project-Access-Token": at})):
        try:
            out = _probe(probe, hdr)
            if (out.get("data") or {}).get("projectToken"):
                _MODE = "bearer-pt" if mode == "bearer" else "project-as-api"
                print(f"railway auth mode: {mode} projectToken OK")
                return _MODE
        except Exception as exc:
            print(f"railway auth probe {mode}: {type(exc).__name__}")
    try:
        out = _probe("query { projects(first: 5) { edges { node { id } } } }",
                     {"Authorization": f"Bearer {at}"})
        if ((out.get("data") or {}).get("projects") or {}).get("edges"):
            _MODE = "account"
            print("railway auth mode: account bearer")
            return _MODE
    except Exception as exc:
        print(f"railway auth probe account: {type(exc).__name__}")
    sys.exit("RAILWAY_API_TOKEN answers neither as project nor account token")


def _headers():
    h = {"Content-Type": "application/json", "User-Agent": "viva-ops/1.0"}
    mode = _detect_mode()
    pt = os.getenv("RAILWAY_TOKEN", "").strip()
    at = os.getenv("RAILWAY_API_TOKEN", "").strip()
    if mode == "project":
        h["Project-Access-Token"] = pt
    elif mode == "project-as-api":
        h["Project-Access-Token"] = at
    else:
        h["Authorization"] = f"Bearer {at}"
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
    # Viva 10-10: account-token-only mode. Under a Bearer account token the
    # projectToken field resolves to null, so the project is resolved by
    # listing account projects (RAILWAY_PROJECT_NAME picks one, else first)
    # and the production environment instead of failing.
    at = os.getenv("RAILWAY_API_TOKEN", "").strip()
    pt = os.getenv("RAILWAY_TOKEN", "").strip()
    if at and not pt:
        dp, ep = gql("query { projects(first: 10) { edges { node { id name "
                     "environments { edges { node { id name } } } } } } }",
                     account=True)
        projs = _edges((dp or {}).get("projects"))
        if projs:
            want = os.getenv("RAILWAY_PROJECT_NAME", "").strip().lower()
            pick = next((p for p in projs
                         if want and str(p.get("name", "")).lower() == want),
                        projs[0])
            envs = _edges(pick.get("environments"))
            env = next((n for n in envs
                        if str(n.get("name", "")).lower() == "production"),
                       envs[0] if envs else None)
            if pick.get("id") and env and env.get("id"):
                print(f"(account mode: project={pick.get('name')})")
                return pick["id"], env["id"]
        print("account project lookup failed:", ep)
        return None, None
    print("projectToken lookup failed:", e)
    return None, None


def _edges(x):
    return [n.get("node") for n in ((x or {}).get("edges") or [])]


def access():
    pid, eid = ids()
    print(f"project_id={pid}\nenvironment_id={eid}")
    if not pid:
        return 1
    # 10-11 v2: minimal field set (the v1 query 400s on the current
    # schema — one of startCommand/numReplicas/region/sleepApplication/
    # cronSchedule/volumeInstances no longer exists there).
    q = """query($id:String!){ project(id:$id){ name createdAt
          environments{ edges{ node{ id name } } }
          services{ edges{ node{ id name
              serviceInstances{ edges{ node{ environmentId
                  latestDeployment{ id status createdAt } } } } } } } } }"""
    d, e = gql(q, {"id": pid})
    for m in e:
        print("  gql:", m)
    p = (d or {}).get("project") or {}
    print(f"\n== project: {p.get('name')}  (created {p.get('createdAt')})")
    envs = {n["id"]: n["name"] for n in _edges(p.get("environments"))}
    print("environments:", ", ".join(f"{v}" + (" *" if k == eid else "") for k, v in envs.items()))
    print("\n== services")
    for s in _edges(p.get("services")):
        _shown = False
        for si in _edges(s.get("serviceInstances")):
            if eid and si.get("environmentId") != eid:
                continue
            ld = si.get("latestDeployment") or {}
            print(f"- {s['name']}  id={s['id']}\n"
                  f"    last deploy: {ld.get('status')} @ {ld.get('createdAt')}")
            dd, de = gql("query($id:String!){ service(id:$id){ serviceDomains"
                         "{ edges{ node{ domain status } } } } }",
                         {"id": s["id"]})
            for dom in _edges((((dd or {}).get("service") or {})
                               .get("serviceDomains"))):
                print(f"    https://{dom.get('domain')}  [{dom.get('status')}]")
            for m in de:
                print("    domains gql:", m)
            _shown = True
        if not _shown:
            print(f"- {s['name']}  id={s['id']}  (no instance in this env)")
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

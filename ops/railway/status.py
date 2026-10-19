import json, os, urllib.request, sys
API="https://backboard.railway.com/graphql/v2"
PID="dfa19d15-6e78-41b5-8a0c-8ccfc3807add"
EID="a787e251-94d1-4665-8ab4-dc9b92a10a2a"
SID="84f5a4ef-117f-4c2d-a460-83bd290ce58a"
def gql(q,v=None):
    body=json.dumps({"query":q,"variables":v or {}}).encode()
    req=urllib.request.Request(API,data=body,method="POST",
        headers={"Authorization":"Bearer "+os.environ["RAILWAY_API_TOKEN"],
                 "Content-Type":"application/json","User-Agent":"viva-ops/1.0"})
    with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read().decode())
d=gql("""query($p:String!,$e:String!,$s:String!){
  deployments(first:4, input:{projectId:$p, environmentId:$e, serviceId:$s}){
    edges{ node{ id status createdAt staticUrl } } } }""",{"p":PID,"e":EID,"s":SID})
for e in (d.get("data",{}).get("deployments",{}) or {}).get("edges",[]):
    n=e["node"]; print(" ",n["status"],n["createdAt"],n.get("staticUrl") or "")
if d.get("errors"): print("ERR",json.dumps(d["errors"])[:300])

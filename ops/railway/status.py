import json, os, urllib.request
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

print("=== deployments ===")
d=gql("""query($p:String!,$e:String!){ deployments(first:5, input:{projectId:$p, environmentId:$e}){
 edges{ node{ id status createdAt } } } }""",{"p":PID,"e":EID})
if d.get("errors"): print("ERR1:",json.dumps(d["errors"])[:300])
for e in ((d.get("data") or {}).get("deployments") or {}).get("edges",[]) or []:
    n=e["node"]; print(" ",n["status"],n["createdAt"],n["id"])

print("=== service instance / domains ===")
d2=gql("""query($p:String!,$e:String!,$s:String!){
 project(id:$p){ service(id:$s){ name
   serviceInstances(environmentId:$e){ edges{ node{ id
     domains{ serviceDomains{ domain } customDomains{ domain } } } } } } } }""",
 {"p":PID,"e":EID,"s":SID})
print(json.dumps(d2)[:900])

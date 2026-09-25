"""Publish replay results as GitHub check runs (text ≤ 65k per run).

The development sandbox cannot download Actions logs/artifacts, so the report
travels back through the Checks API: one `replay-report` run with the markdown
and `replay-trades-k` runs carrying the compact CSV in chunks.
Env: GH_TOKEN, GITHUB_REPOSITORY, GITHUB_SHA.
"""
from __future__ import annotations

import json
import os
import sys

import requests

LIMIT = 60000


def post(name: str, title: str, summary: str, text: str) -> None:
    repo, sha, tok = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"], os.environ["GH_TOKEN"]
    r = requests.post(
        f"https://api.github.com/repos/{repo}/check-runs",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
        data=json.dumps({"name": name, "head_sha": sha, "status": "completed", "conclusion": "neutral",
                         "output": {"title": title[:250], "summary": summary[:60000], "text": text[:LIMIT]}}),
        timeout=30)
    print(name, r.status_code, r.text[:200])


def chunks(s: str, n: int):
    lines, cur = s.splitlines(keepends=True), ""
    for ln in lines:
        if len(cur) + len(ln) > n:
            yield cur
            cur = ""
        cur += ln
    if cur:
        yield cur


def main() -> None:
    md_path, csv_path = sys.argv[1], sys.argv[2]
    md = open(md_path).read() if os.path.exists(md_path) else "no report"
    parts = list(chunks(md, LIMIT))
    post("replay-report", "Walk-forward replay of live setups", parts[0][:LIMIT], "\n".join(parts[1:2]) or "-")
    for i, extra in enumerate(parts[2:], 2):
        post(f"replay-report-{i}", "report continued", "continued", extra)
    fates_path = sys.argv[3] if len(sys.argv) > 3 else "fates.md"
    if os.path.exists(fates_path):
        fparts = list(chunks(open(fates_path).read(), LIMIT))
        post("replay-fates", "Candidate fates (why scenarios die)", fparts[0], "\n".join(fparts[1:2]) or "-")
        for i, extra in enumerate(fparts[2:], 2):
            post(f"replay-fates-{i}", "fates continued", "continued", extra)
    if os.path.exists(csv_path):
        csv = open(csv_path).read()
        header, body = csv.split("\n", 1) if "\n" in csv else (csv, "")
        for k, c in enumerate(chunks(body, LIMIT - len(header) - 10), 1):
            post(f"replay-trades-{k}", f"trades csv part {k}", "csv", header + "\n" + c)


if __name__ == "__main__":
    main()

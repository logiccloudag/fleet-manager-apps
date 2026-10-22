#!/usr/bin/env python3
"""Creates the YouTrack issue of the weekly upstream check (FM-1631) when an
app cannot be regenerated: a major upstream bump or a red gate.

Usage: scripts/youtrack-issue.py [--dry-run] [--dedupe-regex <regex>] <summary> <description-file>

- Deduplicates: when an issue of the project with the tag and a State other
  than Done has the same summary, or a summary that matches
  --dedupe-regex (Python syntax), it prints "exists <id> <url>" and creates
  nothing. The weekly check matches a major upgrade issue per app and target
  major, because its "old" version moves with every update within the
  current major (FM-1731).
- Otherwise it creates a Task (State "Not started") with the description,
  adds the tag and puts it on the current sprint of the board. Prints
  "created <id> <url>".
- --dry-run resolves the project, the tag and the sprint and runs the
  duplicate search, but creates nothing.

Environment:
  YOUTRACK_TOKEN    permanent token (required; the script fails without it,
                    it never skips; never printed)
  YOUTRACK_URL      default https://logiccloud.youtrack.cloud
  YOUTRACK_PROJECT  project short name, default FM
  YOUTRACK_AGILE    board id, default 171-9
  YOUTRACK_TAG      default margo-apps
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

URL = os.environ.get("YOUTRACK_URL", "https://logiccloud.youtrack.cloud").rstrip("/")
PROJECT = os.environ.get("YOUTRACK_PROJECT", "FM")
AGILE = os.environ.get("YOUTRACK_AGILE", "171-9")
TAG = os.environ.get("YOUTRACK_TAG", "margo-apps")


def die(msg):
    print(f"[youtrack-issue] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def api(method, path, body=None):
    token = os.environ.get("YOUTRACK_TOKEN", "")
    if not token:
        die("YOUTRACK_TOKEN is not set (repository secret YOUTRACK_TOKEN)")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{URL}/{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        die(f"{method} {path.split('?')[0]}: HTTP {e.code} {e.read()[:300]!r}")
    return json.loads(raw) if raw else None


def q(value):
    return urllib.parse.quote(value, safe="")


def main(argv):
    dry = "--dry-run" in argv
    args = [a for a in argv[1:] if a != "--dry-run"]
    dedupe = None
    if "--dedupe-regex" in args:
        i = args.index("--dedupe-regex")
        if i + 1 >= len(args):
            die("--dedupe-regex needs a value")
        dedupe = re.compile(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__)
        return 2
    summary, desc_path = args
    with open(desc_path, encoding="utf-8") as f:
        description = f.read()

    projects = api("GET", f"api/admin/projects?fields=id,shortName&$top=100&query={q(PROJECT)}")
    project = next((p for p in projects if p.get("shortName") == PROJECT), None)
    if not project:
        die(f"project {PROJECT} not found")
    tags = api("GET", f"api/issueTags?fields=id,name&$top=100&query={q(TAG)}")
    tag = next((t for t in tags if t.get("name") == TAG), None)
    if not tag:
        die(f"tag {TAG} not found; create it in YouTrack first")
    sprint = (api("GET", f"api/agiles/{AGILE}?fields=currentSprint(id,name)") or {}).get("currentSprint")
    if not sprint:
        die(f"board {AGILE} has no current sprint")

    query = f"project: {PROJECT} tag: {{{TAG}}} State: -Done"
    found = api("GET", f"api/issues?fields=idReadable,summary&$top=200&query={q(query)}")
    dup = next((i for i in found if i.get("summary", "").strip() == summary.strip()
                or (dedupe and dedupe.search(i.get("summary", "")))), None)
    if dup:
        print(f"exists {dup['idReadable']} {URL}/issue/{dup['idReadable']}")
        return 0
    if dry:
        print(f"dry-run: would create a Task in {PROJECT} tagged {TAG} on sprint {sprint.get('name')}: {summary}")
        return 0

    issue = api("POST", "api/issues?fields=id,idReadable", {
        "project": {"id": project["id"]},
        "summary": summary,
        "description": description,
        "customFields": [
            {"name": "Type", "$type": "SingleEnumIssueCustomField", "value": {"name": "Task"}},
            {"name": "State", "$type": "StateIssueCustomField", "value": {"name": "Not started"}},
        ],
    })
    api("POST", f"api/issues/{issue['id']}/tags?fields=id", {"id": tag["id"]})
    api("POST", f"api/agiles/{AGILE}/sprints/{sprint['id']}/issues?fields=id", {"id": issue["id"]})
    print(f"created {issue['idReadable']} {URL}/issue/{issue['idReadable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

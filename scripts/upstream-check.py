#!/usr/bin/env python3
"""Weekly upstream check of the catalog (FM-1631, ADR FM-A-202 decision 5).

Subcommands:

  plan <plan.json> [app-dir...]
      Finds the newest stable upstream version of every pin and writes the
      plan. Per app the action is:
        none        everything is up to date
        regenerate  a patch or minor bump: scripts/upstream-check.py
                    regenerate rewrites the app, the gate decides
        issue       a major bump: a human plans the upgrade
      Prints one line per app.

  regenerate <plan.json> <app-dir>
      Applies the planned bump of one app to the working tree: the pins
      (scripts/charts.tsv, scripts/images.tsv), every image reference
      (app/margo.yaml, chart/values.yaml, compose/compose.yaml), the
      versions (chart version of a wrapper or local chart, revision, compose
      revision, metadata.version), the release notes and the README apps
      table. Prints the commit subject as the last line. The gate
      (scripts/check.sh) decides whether the result is committed; its image
      pin check fails on any reference this missed.

Upstream sources:
  - a mirror chart: its tags (OCI) or its Helm repository index;
  - a wrapper chart: the version of its dependency in the Helm repository
    index;
  - an image with track "tags": the newest upstream tag of the same shape
    (scripts/lib/versions.py);
  - an image with track "chart": the appVersion of the app's new mirror
    chart, with the prefix and suffix of the pinned tag.

Requires python3 with PyYAML, crane and helm.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import versions  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARTS_TSV = os.path.join(ROOT, "scripts", "charts.tsv")
IMAGES_TSV = os.path.join(ROOT, "scripts", "images.tsv")
IMAGE_REGISTRY = os.environ.get("IMAGE_REGISTRY", "ghcr.io/logiccloudag/margo-images")


def log(msg):
    print(f"[upstream-check] {msg}", file=sys.stderr)


def die(msg):
    print(f"[upstream-check] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(*cmd, cwd=None, env=None):
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        die(f"{' '.join(cmd)} failed: {res.stderr.strip()[-500:]}")
    return res.stdout


# ------------------------------------------------------------------ tables

def read_tsv(path, columns):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            rows.append(dict(zip(columns, cols)))
    return rows


CHART_COLS = ("app", "chart", "version", "type", "source", "sha256")
IMAGE_COLS = ("name", "upstream", "tag", "digest", "apps", "track")


def update_tsv(path, key_col, key, changes, columns):
    """Sets columns of the row whose `key_col` is `key`."""
    out, hit = [], False
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                out.append(line)
                continue
            cols = line.rstrip("\n").split("\t")
            row = dict(zip(columns, cols))
            if row[key_col] == key:
                hit = True
                for k, v in changes.items():
                    cols[columns.index(k)] = v
            out.append("\t".join(cols) + "\n")
    if not hit:
        die(f"no row {key} in {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)


# --------------------------------------------------------------- discovery

def oci_tags(repository):
    return run("crane", "ls", repository.removeprefix("oci://")).split()


def helm_repo_versions(url, chart):
    with urllib.request.urlopen(url.rstrip("/") + "/index.yaml", timeout=60) as resp:
        index = yaml.safe_load(resp.read())
    return [e["version"] for e in (index.get("entries") or {}).get(chart) or []]


def chart_candidates(source):
    if source.startswith("oci://"):
        return oci_tags(source)
    url, _, name = source.partition("#")
    return helm_repo_versions(url, name)


def chart_app_version(source, version):
    with tempfile.TemporaryDirectory() as tmp:
        tgz = pull_chart(source, version, tmp)
        out = run("helm", "show", "chart", tgz)
    return str(yaml.safe_load(out).get("appVersion") or "")


def pull_chart(source, version, dest):
    if source.startswith("oci://"):
        run("helm", "pull", source, "--version", version, "-d", dest)
    else:
        url, _, name = source.partition("#")
        run("helm", "pull", name, "--repo", url, "--version", version, "-d", dest)
    tgzs = [f for f in os.listdir(dest) if f.endswith(".tgz")]
    if len(tgzs) != 1:
        die(f"helm pull {source} {version} gave {tgzs}")
    return os.path.join(dest, tgzs[0])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def wrapper_dependency(app):
    chart = load_yaml(os.path.join(ROOT, app, "chart", "Chart.yaml"))
    deps = chart.get("dependencies") or []
    if len(deps) != 1:
        die(f"{app}: a wrapper chart has exactly one dependency, got {len(deps)}")
    return deps[0]


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# -------------------------------------------------------------------- plan

def plan_app(chart_row, image_rows):
    app = chart_row["app"]
    components = []
    chart_latest = None
    if chart_row["type"] == "mirror":
        latest = versions.newest(chart_row["version"], chart_candidates(chart_row["source"]))
        chart_latest = latest
        components.append({
            "kind": "chart", "name": chart_row["chart"], "source": chart_row["source"],
            "current": chart_row["version"], "latest": latest,
            "bump": versions.classify(chart_row["version"], latest),
        })
    elif chart_row["type"] == "wrapper":
        dep = wrapper_dependency(app)
        source = f"{dep['repository']}#{dep['name']}"
        latest = versions.newest(str(dep["version"]), chart_candidates(source))
        components.append({
            "kind": "dependency", "name": dep["name"], "source": source,
            "current": str(dep["version"]), "latest": latest,
            "bump": versions.classify(str(dep["version"]), latest),
        })
    for img in image_rows:
        if img.get("track") == "chart":
            if chart_row["type"] != "mirror":
                die(f"{img['name']}: track chart needs a mirror chart, {app} has {chart_row['type']}")
            if chart_latest == chart_row["version"]:
                latest = img["tag"]
            else:
                app_version = chart_app_version(chart_row["source"], chart_latest)
                latest = versions.retag(img["tag"], app_version)
        elif img.get("track") == "tags":
            latest = versions.newest(img["tag"], oci_tags(img["upstream"]))
        else:
            die(f"{img['name']}: unknown track {img.get('track')!r} in scripts/images.tsv")
        components.append({
            "kind": "image", "name": img["name"], "upstream": img["upstream"],
            "current": img["tag"], "latest": latest, "bump": versions.classify(img["tag"], latest),
        })
    bump = versions.max_bump(*[c["bump"] for c in components])
    action = {"none": "none", "major": "issue"}.get(bump, "regenerate")
    return {"app": app, "id": load_yaml(os.path.join(ROOT, app, "app", "margo.yaml"))["id"],
            "bump": bump, "action": action, "components": components}


def cmd_plan(out, apps):
    charts = read_tsv(CHARTS_TSV, CHART_COLS)
    images = read_tsv(IMAGES_TSV, IMAGE_COLS)
    result = []
    for row in charts:
        if apps and row["app"] not in apps:
            continue
        rows = [i for i in images if row["app"] in i["apps"].split(",")]
        entry = plan_app(row, rows)
        result.append(entry)
        changes = ", ".join(f"{c['kind']} {c['name']} {c['current']} -> {c['latest']} ({c['bump']})"
                            for c in entry["components"] if c["bump"] != "none")
        print(f"{entry['app']}\t{entry['action']}\t{changes or 'up to date'}")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)


# -------------------------------------------------------------- regenerate

def edit(path, fn):
    with open(path, encoding="utf-8") as f:
        old = f.read()
    new = fn(old)
    if new != old:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    return new != old


def sub_once(text, pattern, repl, what, flags=re.M):
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        die(f"could not update {what}")
    return new


def set_revision(margo_path, component, revision):
    """Sets properties.revision of one component in app/margo.yaml."""
    def fn(text):
        pattern = (rf"(^\s*- name: {re.escape(component)}\n(?:\s+(?:#.*|\w+:.*)\n)*?"
                   rf"\s+revision: )\"[^\"]*\"")
        return sub_once(text, pattern, rf'\g<1>"{revision}"', f"revision of {component}")
    edit(margo_path, fn)


def component_revision(doc, ptype):
    comps = [c for p in doc["deploymentProfiles"] if p["type"] == ptype for c in p["components"]]
    return (comps[0]["name"], comps[0]["properties"]["revision"]) if comps else (None, None)


def replace_image_refs(app, name, old_tag, old_digest, new_tag, new_digest):
    """Rewrites every reference of the image in the app's files. Returns the
    number of changed files; the image pin check of scripts/check.sh fails on
    any reference left behind."""
    old_hex, new_hex = old_digest.split(":", 1)[1], new_digest.split(":", 1)[1]
    files = [os.path.join(ROOT, app, rel) for rel in
             ("app/margo.yaml", "chart/values.yaml", "compose/compose.yaml")]
    changed = 0

    def fn(text):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                continue
            if old_hex in line:
                # A full reference, "<tag>@sha256:<hex>", a digest or a bare hex.
                line = line.replace(f"{old_tag}@{old_digest}", f"{new_tag}@{new_digest}")
                line = line.replace(old_hex, new_hex)
            elif re.match(rf"^\s*tag:\s*\"?{re.escape(old_tag)}\"?\s*$", line):
                line = line.replace(old_tag, new_tag)
            elif (re.match(rf"^\s*value:\s*\"{re.escape(old_tag)}\"\s*$", line)
                  and i > 0 and re.match(r"^\s*imageTag:\s*$", lines[i - 1])):
                line = line.replace(old_tag, new_tag)
            lines[i] = line
        return "\n".join(lines)

    for path in files:
        if os.path.isfile(path) and edit(path, fn):
            changed += 1
    return changed


def set_chart_version(app, version, app_version_change=None):
    path = os.path.join(ROOT, app, "chart", "Chart.yaml")

    def fn(text):
        text = sub_once(text, r"^version: .*$", f"version: {version}", f"{app} Chart.yaml version")
        if app_version_change:
            old, new = app_version_change
            text = re.sub(rf'^appVersion: "?{re.escape(old)}"?$', f'appVersion: "{new}"', text, count=1, flags=re.M)
        return text
    edit(path, fn)


def update_readme_row(app_id, replacements):
    path = os.path.join(ROOT, "README.md")

    def fn(text):
        out = []
        for line in text.split("\n"):
            if line.startswith(f"| `{app_id}` |"):
                for old, new in replacements:
                    line = line.replace(old, new)
            out.append(line)
        return "\n".join(out)
    edit(path, fn)


def add_release_notes(app, version, items):
    path = os.path.join(ROOT, app, "app", "release-notes.md")
    block = f"## {version}\n\n" + "".join(f"- {i}\n" for i in items) + "\n"
    edit(path, lambda t: t.replace("# Release Notes\n\n", "# Release Notes\n\n" + block, 1))


def wrapper_dependency_update(app, dep_name, new_version):
    chart_dir = os.path.join(ROOT, app, "chart")

    def fn(text):
        pattern = rf"(^\s*- name: {re.escape(dep_name)}\n\s+version: )\S+"
        return sub_once(text, pattern, rf"\g<1>{new_version}", f"{app} dependency {dep_name}")
    edit(os.path.join(chart_dir, "Chart.yaml"), fn)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, HELM_REPOSITORY_CONFIG=os.path.join(tmp, "repositories.yaml"),
                   HELM_REPOSITORY_CACHE=os.path.join(tmp, "cache"))
        dep = wrapper_dependency(app)
        run("helm", "repo", "add", "dep1", dep["repository"], env=env)
        run("helm", "dependency", "update", chart_dir, env=env)
    tgz = os.path.join(chart_dir, "charts", f"{dep_name}-{new_version}.tgz")
    if not os.path.isfile(tgz):
        die(f"{app}: helm dependency update did not produce {tgz}")
    return sha256_file(tgz)


def cmd_regenerate(plan_path, app):
    with open(plan_path, encoding="utf-8") as f:
        entry = next((e for e in json.load(f) if e["app"] == app), None)
    if entry is None:
        die(f"{app} is not in {plan_path}")
    if entry["action"] != "regenerate":
        die(f"{app}: planned action is {entry['action']}, not regenerate")
    level = entry["bump"]
    margo_path = os.path.join(ROOT, app, "app", "margo.yaml")
    doc = load_yaml(margo_path)
    chart_row = next(r for r in read_tsv(CHARTS_TSV, CHART_COLS) if r["app"] == app)
    image_rows = {r["name"]: r for r in read_tsv(IMAGES_TSV, IMAGE_COLS)}
    helm_component, helm_revision = component_revision(doc, "helm")
    compose_component, compose_revision = component_revision(doc, "compose")
    notes, readme, subject = [], [], None
    chart_version = chart_row["version"]
    image_changed = False

    for comp in entry["components"]:
        if comp["bump"] == "none":
            continue
        subject = subject or (comp["current"], comp["latest"])
        if comp["kind"] == "chart":
            with tempfile.TemporaryDirectory() as tmp:
                sha = sha256_file(pull_chart(comp["source"], comp["latest"], tmp))
            update_tsv(CHARTS_TSV, "app", app, {"version": comp["latest"], "sha256": sha}, CHART_COLS)
            set_revision(margo_path, helm_component, comp["latest"])
            readme.append((f"`{comp['name']}` {comp['current']}", f"`{comp['name']}` {comp['latest']}"))
            readme.append((f"{comp['current']} |", f"{comp['latest']} |"))
            notes.append(f"Chart: {comp['name']} {comp['current']} → {comp['latest']} (unchanged mirror).")
            chart_version = comp["latest"]
        elif comp["kind"] == "dependency":
            sha = wrapper_dependency_update(app, comp["name"], comp["latest"])
            chart_version = versions.bump(chart_row["version"], level)
            set_chart_version(app, chart_version)
            update_tsv(CHARTS_TSV, "app", app, {"version": chart_version, "sha256": sha}, CHART_COLS)
            set_revision(margo_path, helm_component, chart_version)
            readme.append((f"{comp['name']}` {comp['current']}", f"{comp['name']}` {comp['latest']}"))
            notes.append(f"Chart: {chart_row['chart']} {chart_row['version']} → {chart_version}, "
                         f"dependency {comp['name']} {comp['current']} → {comp['latest']}.")
        elif comp["kind"] == "image":
            row = image_rows[comp["name"]]
            new_digest = run("crane", "digest", f"{row['upstream']}:{comp['latest']}").strip()
            if not re.match(r"^sha256:[0-9a-f]{64}$", new_digest):
                die(f"{comp['name']}: unexpected digest {new_digest!r}")
            changed = replace_image_refs(app, comp["name"], row["tag"], row["digest"], comp["latest"], new_digest)
            if changed == 0:
                die(f"{app}: no reference of {comp['name']}:{row['tag']} found")
            update_tsv(IMAGES_TSV, "name", comp["name"], {"tag": comp["latest"], "digest": new_digest}, IMAGE_COLS)
            readme.append((f"{row['upstream'].removeprefix('docker.io/')}:{row['tag']}",
                           f"{row['upstream'].removeprefix('docker.io/')}:{comp['latest']}"))
            # The application column: "Traefik v3.7.14, copy of ...".
            old_v, new_v = versions.shape(row["tag"]), versions.shape(comp["latest"])
            readme.append((f" {old_v[0]}{'.'.join(map(str, old_v[1]))},",
                           f" {new_v[0]}{'.'.join(map(str, new_v[1]))},"))
            notes.append(f"Image: `{IMAGE_REGISTRY}/{comp['name']}:{comp['latest']}`, a copy of "
                         f"`{row['upstream']}:{comp['latest']}` ({comp['current']} before).")
            image_changed = True
            if chart_row["type"] in ("local", "wrapper"):
                # appVersion is the tag without its suffix ("2.1.2" for
                # "2.1.2-alpine", "v3.7.14" for "v3.7.14").
                cur = versions.shape(row["tag"])
                new = versions.shape(comp["latest"])
                old_app = cur[0] + ".".join(map(str, cur[1]))
                new_app = new[0] + ".".join(map(str, new[1]))
                if chart_version == chart_row["version"]:
                    chart_version = versions.bump(chart_row["version"], level)
                set_chart_version(app, chart_version, (old_app, new_app))
                update_tsv(CHARTS_TSV, "app", app, {"version": chart_version}, CHART_COLS)
                set_revision(margo_path, helm_component, chart_version)

    if chart_row["type"] == "local" and chart_version != chart_row["version"]:
        notes.append(f"Chart: {chart_row['chart']} {chart_row['version']} → {chart_version}.")
    if chart_row["type"] in ("local", "wrapper") and chart_version != chart_row["version"]:
        readme.append((f"`{chart_row['chart']}` {chart_row['version']}", f"`{chart_row['chart']}` {chart_version}"))
    if image_changed and compose_component:
        new_rev = versions.bump(compose_revision, level)
        set_revision(margo_path, compose_component, new_rev)
        notes.append(f"Compose package {new_rev} with the new image.")
    meta_old = str(doc["metadata"]["version"])
    meta_new = versions.bump(meta_old, level)
    edit(margo_path, lambda t: sub_once(t, rf'^(  version: )"{re.escape(meta_old)}"', rf'\g<1>"{meta_new}"',
                                        "metadata.version"))
    notes.append("Automatic update by the weekly upstream check (FM-1631).")
    add_release_notes(app, meta_new, notes)
    update_readme_row(entry["id"], readme)
    print(f"chore({entry['id']}): upstream {subject[0]} → {subject[1]}")


def main(argv):
    if len(argv) >= 3 and argv[1] == "plan":
        cmd_plan(argv[2], set(a.rstrip("/") for a in argv[3:]))
    elif len(argv) == 4 and argv[1] == "regenerate":
        cmd_regenerate(argv[2], argv[3].rstrip("/"))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

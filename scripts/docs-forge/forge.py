"""docs-forge: capture -> evidence -> export -> publish/(commit).

CLI: forge.py run <profile.json> [--skip ...] [--commit] [--publish]
     forge.py capture <profile.json> [--base-url URL]
     forge.py export <profile.json> [--slug name]
     forge.py publish <profile.json>

Landed from the mirrors engine (D:/mirrors); the 2026-08-26 run produced the
current pages - see docs/screenshots/forge-report.json for that run.

Design rules (paid for on 2026-08-26, see AGENTS.md):
- agents/LLMs never invent numbers: evidence text comes from tools verbatim
- screenshot manifests fail on blank (<min_bytes) and byte-identical frames
- Mintlify: docs.json (navigation OBJECT, theme 'mint'), assets at SITE ROOT
  (public/ is not served), dev server caches its manifest (restart required)
- secrets live in env files referenced by the profile, never in the repo
- relative paths in a profile resolve against its "root", not the CWD
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime


def _resolve(root: str, p: str) -> str:
    return os.path.normpath(os.path.join(root, p)) if not os.path.isabs(p) else p


def load_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    if profile.get("root"):
        base = _resolve(base, profile["root"])
    for field in ("output_dir", "site_dir", "guide_file"):
        if field in profile:
            profile[field] = _resolve(base, profile[field])
    git = profile.setdefault("git", {})
    if git.get("repo"):
        git["repo"] = _resolve(base, git["repo"])
    pw = ((profile.get("login") or {}).get("password") or {})
    if pw.get("env_file"):
        pw["env_file"] = _resolve(base, pw["env_file"])
    return profile


# ---------------------------------------------------------------- capture ---
def _password(profile: dict) -> str:
    spec = profile["login"]["password"]
    with open(spec["env_file"], encoding="utf-8") as f:
        for line in f:
            if line.startswith(spec["key"] + "="):
                return line.split("=", 1)[1].strip()
    raise SystemExit(f"no {spec['key']} in {spec['env_file']}")


def capture(profile: dict, base_override: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    base = base_override or profile["base_url"]
    out = profile["output_dir"]
    os.makedirs(out, exist_ok=True)
    w, h = profile.get("viewport", [1280, 800])
    login, sel = profile.get("login") or {}, (profile.get("login") or {}).get("selectors", {})

    def shoot(page, name: str) -> None:
        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(out, name + ".png"), full_page=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": w, "height": h}).new_page()
        for shot in profile["shots"]:
            if shot.get("pre_auth"):
                page.goto(base + shot["path"], wait_until="domcontentloaded")
                shoot(page, shot["name"])
        if login:
            page.goto(base + "/", wait_until="domcontentloaded")
            page.locator(sel["user"]).first.fill(login.get("user", "admin"))
            page.locator(sel["password"]).first.fill(_password(profile))
            page.locator(sel["submit"]).first.click()
            page.wait_for_selector(login.get("success", "nav"), timeout=20000)
            page.wait_for_timeout(800)
        for shot in profile["shots"]:
            if not shot.get("pre_auth"):
                page.goto(base + shot["path"], wait_until="domcontentloaded")
                shoot(page, shot["name"])
        theme = profile.get("theme")
        if theme:
            page.goto(base + theme.get("path", "/"), wait_until="domcontentloaded")
            page.wait_for_timeout(600)
            page.locator(theme["selector"]).first.click()
            shoot(page, theme["name"])
            if theme.get("toggle_back"):
                page.locator(theme["selector"]).first.click()
        browser.close()

    manifest, problems, sizes = [], [], {}
    for fn in sorted(os.listdir(out)):
        if fn.endswith(".png"):
            b = open(os.path.join(out, fn), "rb").read()
            manifest.append({"file": fn, "bytes": len(b),
                             "sha1": hashlib.sha1(b).hexdigest()[:12]})
    for m in manifest:
        if m["bytes"] < profile.get("min_bytes", 8000):
            problems.append(f"{m['file']}: {m['bytes']}B below minimum (blank?)")
        if m["bytes"] in sizes:
            problems.append(f"{m['file']}: byte-size twin of {sizes[m['bytes']]}")
        else:
            sizes[m["bytes"]] = m["file"]
    report = {"generated": datetime.now().isoformat(timespec="seconds"),
              "base": base, "shots": manifest,
              "ok": not problems, "problems": problems}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    return report


# --------------------------------------------------------------- evidence ---
def evidence(profile: dict) -> dict:
    r = subprocess.run(profile["evidence_command"], shell=True,
                       cwd=profile.get("git", {}).get("repo") or None,
                       capture_output=True, text=True, timeout=180)
    text = ((r.stdout or "") + (r.stderr or "")).strip()
    return {"exit": r.returncode, "output": text[-8000:]}


# ----------------------------------------------------------------- export ---
def _to_mdx(guide_md: str, title: str, description: str) -> str:
    body = re.sub(r"^# .*?\n", "", guide_md, count=1)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return (f"---\ntitle: \"{title}\"\ndescription: \"{description}\"\n"
            f"date: {date.today().isoformat()}\n"
            "generated-by: docs-forge (from docs/admin-guide.md - do not edit)\n"
            "---\n\n" + body)


def _merge_nav(site: str, slug: str, group: str) -> None:
    cfg = os.path.join(site, "docs.json")
    if os.path.exists(cfg):
        mint = json.load(open(cfg, encoding="utf-8"))
    else:
        mint = {"$schema": "https://mintlify.com/docs.json", "name": "Project Docs",
                "theme": "mint", "favicon": "/favicon.png",
                "colors": {"primary": "#0F172A", "light": "#64748B", "dark": "#0F172A"},
                "navigation": {"pages": []}}
    nav = mint.setdefault("navigation", {}).setdefault("pages", [])
    tab = next((t for t in nav if str(t.get("group", "")).lower() == group.lower()), None)
    if tab is None:
        tab = {"group": group, "pages": []}
        nav.append(tab)
    if slug not in tab["pages"]:
        tab["pages"].append(slug)
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(mint, f, indent=2, ensure_ascii=False)
        f.write("\n")


def export_mintlify(profile: dict, slug: str | None = None) -> dict:
    site = profile["site_dir"]
    slug = slug or profile.get("slug") or profile.get("name", "project") + "-admin"
    guide, shots_dir = profile["guide_file"], profile["output_dir"]

    os.makedirs(os.path.join(site, "screenshots"), exist_ok=True)  # ROOT, not public/
    copied = 0
    if os.path.isdir(shots_dir):
        for fn in sorted(os.listdir(shots_dir)):
            if fn.endswith(".png"):
                shutil.copy2(os.path.join(shots_dir, fn),
                             os.path.join(site, "screenshots", fn))
                copied += 1
    msrc = os.path.join(shots_dir, "manifest.json")
    if os.path.exists(msrc):
        shutil.copy2(msrc, os.path.join(site, "screenshots", "manifest.json"))

    raw = open(guide, encoding="utf-8").read()
    md = raw.replace("](screenshots/", "](/screenshots/")
    title = re.search(r"^# (.+)$", raw, re.M).group(1)
    with open(os.path.join(site, slug + ".mdx"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write(_to_mdx(md, title,
                        f"{profile.get('name', 'project')} admin guide (validated)"))
    _merge_nav(site, slug, profile.get("docs_group", profile.get("name", "Projects")))
    return {"site": site, "page": slug + ".mdx", "screenshots_copied": copied}


# ---------------------------------------------------------------- publish ---
def publish_site(profile: dict) -> dict:
    """Mirror site_dir into the public docs-only repo, commit, push (Option B)."""
    pub = profile["git"]["publish"]
    site, repo = profile["site_dir"], pub["repo"]
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise SystemExit(f"publish repo {repo} is not a git clone - clone it first")

    keep = {".git", "README.md", "CNAME"}
    for name in os.listdir(repo):
        if name in keep:
            continue
        p = os.path.join(repo, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    for name in os.listdir(site):
        s = os.path.join(site, name)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(repo, name), dirs_exist_ok=True)
        else:
            shutil.copy2(s, os.path.join(repo, name))

    subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
    src = subprocess.run(["git", "-C", profile["git"]["repo"], "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True)
    sha = src.stdout.strip()
    r = subprocess.run(["git", "-C", repo, "commit", "-m",
                        f"docs: forge publish {date.today().isoformat()} from iag@{sha}"],
                       capture_output=True, text=True)
    pushed = None
    if r.returncode == 0 and pub.get("push_url"):
        url, tok = pub["push_url"], os.environ.get(pub.get("token_env", ""), "")
        if tok:
            url = url.replace("https://", f"https://{tok}@")
        p = subprocess.run(["git", "-C", repo, "push", url, pub.get("branch", "main")],
                           capture_output=True, text=True)
        pushed = {"exit": p.returncode, "tail": (p.stdout + p.stderr)[-300:]}
    return {"repo": repo, "commit": (r.stdout + r.stderr).strip()[-300:], "push": pushed}

# ------------------------------------------------------------------ commit ---
def git_commit(profile: dict, message: str) -> str:
    repo = profile["git"]["repo"]
    branch = profile["git"].get("branch")
    if branch:
        subprocess.run(["git", "-C", repo, "checkout", branch],
                       capture_output=True, text=True)
    for rel in [os.path.relpath(profile["guide_file"], repo),
                os.path.relpath(profile["output_dir"], repo),
                os.path.relpath(profile["site_dir"], repo)]:
        subprocess.run(["git", "-C", repo, "add", rel], capture_output=True)
    r = subprocess.run(["git", "-C", repo, "commit", "-m", message],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()[-500:]


# --------------------------------------------------------------------- run ---
def run(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    skip = set(args.skip or [])
    report = {"profile": profile.get("name"),
              "generated": datetime.now().isoformat(timespec="seconds")}

    if "capture" not in skip and profile.get("shots"):
        m = capture(profile, args.base_url)
        report["capture"] = {"ok": m["ok"], "shots": len(m["shots"]),
                             "problems": m["problems"]}
        if not m["ok"]:
            report["verdict"] = "FAIL: capture problems — fix before publishing"
    elif "capture" not in skip:
        report["capture"] = {"ok": True, "shots": 0,
                             "note": "no shots in profile (static mode)"}
    if "evidence" not in skip:
        e = evidence(profile)
        report["evidence"] = {"exit": e["exit"]}
    if "export" not in skip:
        x = export_mintlify(profile, args.slug)
        report["export"] = x
    if "commit" not in skip and args.commit:
        msg = f"docs: forge refresh {date.today().isoformat()} ({profile.get('name')})"
        report["commit"] = git_commit(profile, msg)
    if args.publish:
        report["publish"] = publish_site(profile)

    report.setdefault("verdict", "OK")
    out = os.path.join(profile["output_dir"], "forge-report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1)[:4000])
    return 0 if report["verdict"] == "OK" else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="docs-forge",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="full pipeline: capture+evidence+export(+commit/publish)")
    r.add_argument("profile")
    r.add_argument("--skip", action="append",
                   choices=["capture", "evidence", "export", "commit"])
    r.add_argument("--base-url")
    r.add_argument("--slug")
    r.add_argument("--commit", action="store_true")
    r.add_argument("--publish", action="store_true")
    r.set_defaults(fn=run)
    c = sub.add_parser("capture", help="screenshots only (writes manifest.json)")
    c.add_argument("profile")
    c.add_argument("--base-url")
    c.set_defaults(fn=lambda a: (_print(capture(load_profile(a.profile), a.base_url)), 0)[1])
    e = sub.add_parser("export", help="Mintlify export only")
    e.add_argument("profile")
    e.add_argument("--slug")
    e.set_defaults(fn=lambda a: (_print(export_mintlify(load_profile(a.profile), a.slug)), 0)[1])
    p = sub.add_parser("publish", help="sync site_dir to the public docs repo (+commit/push)")
    p.add_argument("profile")
    p.set_defaults(fn=lambda a: (_print(publish_site(load_profile(a.profile))), 0)[1])
    args = ap.parse_args(argv)
    return args.fn(args)


def _print(obj) -> None:
    print(json.dumps(obj, indent=1)[:3000])


if __name__ == "__main__":
    sys.exit(main())

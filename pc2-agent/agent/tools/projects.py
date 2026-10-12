"""Project discovery and confirm-once registration (app flows, redesign step 3).

- find_projects (risk 0): git repos under the owner's usual folders (home, Desktop, Documents, OneDrive, the
  projects root), at most 3 levels deep; cached so the 5-second heartbeat stays cheap.
- register_project (risk 3, approval): the AI may work on that repo from now on. The path must be one the
  scan found (inside the scan roots, a real git repo); the name must be new.
- create_project (risk 3, approval): a new folder under the projects root with `git init` and a README.

Registrations live in <data dir>/projects.json and are merged into the config at startup; the projects in
agent_config.local.json always win.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from voice_contracts.models import ToolResult
from voice_contracts.tools import CreateProjectArgs, NoArgs, RegisterProjectArgs

from ..config import AgentConfig, ProjectEntry
from . import ToolContext, register
from .code import CodeError, _git

SCAN_DEPTH = 3
SCAN_LIMIT = 60
CACHE_TTL_S = 600
_SKIP = {"node_modules", ".venv", "venv", "__pycache__", "dist", "build", "AppData", "Application Data",
         "site-packages", "Program Files", "Windows", "$Recycle.Bin", ".cache", ".cargo", ".rustup", ".npm",
         ".vscode", ".cursor", "Library", "go", "scoop"}
_cache: dict[str, Any] = {"at": 0.0, "repos": [], "running": False}
_lock = threading.Lock()


def projects_root(cfg: AgentConfig) -> Path:
    return Path(os.path.expandvars(cfg.projects_root)).expanduser()


def scan_roots(cfg: AgentConfig) -> list[Path]:
    home = Path(os.path.expanduser("~"))
    cands = [Path(os.path.expandvars(r)).expanduser() for r in cfg.project_scan_roots] or [
        home, home / "Desktop", home / "Documents", home / "OneDrive" / "Desktop", home / "OneDrive" / "Documents",
        home / "source" / "repos"]
    cands.append(projects_root(cfg))
    out: list[Path] = []
    for c in cands:
        r = c.resolve()
        if r.is_dir() and r not in out:
            out.append(r)
    return out


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]+", "-", name.lower()).strip("-_")
    return (s or "project")[:32]


def scan(cfg: AgentConfig) -> list[dict[str, str]]:
    registered = {Path(e.path).resolve() for e in cfg.projects.values()}
    found: list[dict[str, str]] = []
    seen: set[Path] = set()

    def walk(d: Path, depth: int) -> None:
        if len(found) >= SCAN_LIMIT or depth > SCAN_DEPTH:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for p in entries:
            if len(found) >= SCAN_LIMIT:
                return
            try:
                if not p.is_dir() or p.is_symlink() or p.name.startswith(".") or p.name in _SKIP:
                    continue
                rp = p.resolve()
                if rp in seen:
                    continue
                seen.add(rp)
                if (rp / ".git").exists():
                    if rp not in registered:
                        found.append({"name": _slug(p.name), "label": p.name, "path": str(rp)})
                    continue  # never look inside a repo
            except OSError:
                continue
            walk(p, depth + 1)

    # Most specific roots first: walking home first would mark OneDrive/Desktop as seen at depth 2 and stop
    # one level short of repos that the Desktop root itself reaches (live: voice-pc-control was missed).
    for root in sorted(scan_roots(cfg), key=lambda r: len(r.parts), reverse=True):
        walk(root, 1)
    names: set[str] = set(cfg.projects)
    for r in found:  # unique names: "portfolio", "portfolio-2"
        base, n = r["name"], 2
        while r["name"] in names:
            r["name"] = f"{base[:29]}-{n}"
            n += 1
        names.add(r["name"])
    return found


def discovered(cfg: AgentConfig, wait: bool = False) -> list[dict[str, str]]:
    """Cached scan; refreshed in the background so status calls never block on the disk."""
    with _lock:
        fresh = time.time() - _cache["at"] < CACHE_TTL_S
        start = not fresh and not _cache["running"]
        if start:
            _cache["running"] = True

    def refresh() -> None:
        try:
            repos = scan(cfg)
            with _lock:
                _cache.update(at=time.time(), repos=repos)
        finally:
            with _lock:
                _cache["running"] = False

    if start:
        if wait:
            refresh()
        else:
            threading.Thread(target=refresh, name="project-scan", daemon=True).start()
    with _lock:
        return list(_cache["repos"])


def invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0


def _registry_file(cfg: AgentConfig) -> Path:
    return Path(cfg.data_dir) / "projects.json"


def load_registered(cfg: AgentConfig) -> None:
    """Merge projects registered from the phone into the config (the config file's own entries win)."""
    f = _registry_file(cfg)
    if not f.exists():
        return
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return
    for name, e in data.items():
        if name not in cfg.projects and isinstance(e, dict) and e.get("path"):
            cfg.projects[name] = ProjectEntry(path=e["path"], base_branch=e.get("base_branch", "main"))


def _save(cfg: AgentConfig, name: str, path: Path, base: str) -> None:
    f = _registry_file(cfg)
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    data[name] = {"path": str(path), "base_branch": base, "registered_at": time.time()}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    cfg.projects[name] = ProjectEntry(path=str(path), base_branch=base)
    invalidate()


def _inside(p: Path, roots: list[Path]) -> bool:
    return any(p == r or r in p.parents for r in roots)


@register("find_projects")
def find_projects(args: NoArgs, ctx: ToolContext) -> ToolResult:
    return ToolResult(ok=True, verified=True, data={"registered": sorted(ctx.cfg.projects),
                                                    "found": discovered(ctx.cfg, wait=True)})


@register("register_project")
def register_project(args: RegisterProjectArgs, ctx: ToolContext) -> ToolResult:
    if args.name in ctx.cfg.projects:
        return ToolResult(ok=False, error=f"a project called '{args.name}' is already registered")
    p = Path(args.path).resolve()
    if not _inside(p, scan_roots(ctx.cfg)) or not p.is_dir() or not (p / ".git").exists():
        return ToolResult(ok=False, error="that folder is not a git repo in your usual folders")
    if any(Path(e.path).resolve() == p for e in ctx.cfg.projects.values()):
        return ToolResult(ok=False, error="that folder is already registered")
    try:
        base = _git(p, "rev-parse", "--abbrev-ref", "HEAD").strip() or "main"
    except CodeError as e:
        return ToolResult(ok=False, error=str(e))
    _save(ctx.cfg, args.name, p, base)
    return ToolResult(ok=True, verified=args.name in ctx.cfg.projects,
                      data={"project": args.name, "path": str(p), "base_branch": base})


@register("create_project")
def create_project(args: CreateProjectArgs, ctx: ToolContext) -> ToolResult:
    if args.name in ctx.cfg.projects:
        return ToolResult(ok=False, error=f"a project called '{args.name}' already exists")
    root = projects_root(ctx.cfg)
    p = (root / args.name).resolve()
    if p.parent != root.resolve():
        return ToolResult(ok=False, error="bad project name")
    if p.exists():
        return ToolResult(ok=False, error=f"{p} already exists")
    p.mkdir(parents=True)
    (p / "README.md").write_text(f"# {args.name}\n\n{args.description}\n".rstrip() + "\n", encoding="utf-8")
    try:
        _git(p, "init", "-q", "-b", "main")
        _git(p, "add", "README.md")
        _git(p, "commit", "-q", "-m", "Start project (created from the phone)")
    except CodeError as e:
        return ToolResult(ok=False, error=str(e))
    _save(ctx.cfg, args.name, p, "main")
    return ToolResult(ok=True, verified=(p / ".git").exists(),
                      data={"project": args.name, "path": str(p), "base_branch": "main"})

"""Phase 3 coding tools (doc §16.1, US-501..505): registered projects only, safe paths, git safety net.

Safety model:
- Only projects listed in the agent config; every path is resolved and must stay inside the project
  (no '..', no symlink escape, no .git internals) — TC-S04.
- Edits never touch the base branch: the first edit creates `ai/<timestamp>` from a CLEAN base and every
  edit is a checkpoint commit there (US-503). `revert_changes` returns to the base and deletes the branch.
- Tests run only the project's configured argv (no shell, no model-supplied command) — US-504.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

from voice_contracts.models import ToolResult
from voice_contracts.tools import EditFileArgs, ListFilesArgs, ProjectArgs, ReadFileArgs, SearchCodeArgs

from . import ToolContext, register

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".idea", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", ".next", "coverage"}
MAX_READ_BYTES = 200_000
AGENT_GIT_ENV = {"GIT_AUTHOR_NAME": "Voice PC Agent", "GIT_AUTHOR_EMAIL": "agent@voice-pc.local",
                 "GIT_COMMITTER_NAME": "Voice PC Agent", "GIT_COMMITTER_EMAIL": "agent@voice-pc.local"}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]


class CodeError(Exception):
    pass


def _project(ctx: ToolContext, name: str) -> Any:
    entry = ctx.cfg.projects.get(name)
    if entry is None:
        raise CodeError(f"project '{name}' is not registered")
    root = Path(entry.path).resolve()
    if not root.is_dir():
        raise CodeError(f"project folder not found: {root}")
    return entry, root


def _resolve(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise CodeError("path escapes the project")
    if ".git" in p.relative_to(root).parts:
        raise CodeError("git internals are not accessible")
    return p


def _git(root: Path, *args: str, timeout: float = 30) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",  # noqa: S603,S607
                       errors="replace", timeout=timeout, env={**os.environ, **AGENT_GIT_ENV},
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise CodeError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def _branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _state_file(ctx: ToolContext) -> Path:
    return Path(ctx.cfg.data_dir) / "ai_branches.json"


def _state(ctx: ToolContext) -> dict[str, Any]:
    f = _state_file(ctx)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _save_state(ctx: ToolContext, state: dict[str, Any]) -> None:
    f = _state_file(ctx)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _code_tool(fn):  # type: ignore[no-untyped-def]
    def wrapper(args, ctx: ToolContext) -> ToolResult:  # type: ignore[no-untyped-def]
        try:
            return fn(args, ctx)
        except CodeError as e:
            return ToolResult(ok=False, error=str(e))
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error="timed out")
        except (OSError, UnicodeError) as e:
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}"[:300])
    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------- read-only
@register("open_project")
@_code_tool
def open_project(args: ProjectArgs, ctx: ToolContext) -> ToolResult:
    entry, root = _project(ctx, args.project)
    ide = ctx.cfg.apps.get(entry.ide)
    if ide is None or not ide.argv:
        raise CodeError(f"IDE '{entry.ide}' is not configured in apps")
    ctx.launcher.launch([*ide.argv, str(root)])
    seen = ctx.wait_until(lambda: ctx.launcher.is_running(ide.process), ctx.cfg.verify_timeout_s)
    return ToolResult(ok=True, verified=seen, data={"project": args.project, "ide": entry.ide},
                      error=None if seen else "IDE did not start")


@register("list_files")
@_code_tool
def list_files(args: ListFilesArgs, ctx: ToolContext) -> ToolResult:
    _, root = _project(ctx, args.project)
    base = _resolve(root, args.subdir) if args.subdir else root
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = Path(dirpath).relative_to(root)
        if len(rel_dir.parts) - (len(Path(args.subdir).parts) if args.subdir else 0) >= 3:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for d in dirnames:
            out.append((rel_dir / d).as_posix() + "/")
        for f in sorted(filenames):
            out.append((rel_dir / f).as_posix())
        if len(out) >= 300:
            break
    return ToolResult(ok=True, verified=True, data={"project": args.project, "files": out[:300],
                                                    "truncated": len(out) > 300})


@register("read_file")
@_code_tool
def read_file(args: ReadFileArgs, ctx: ToolContext) -> ToolResult:
    _, root = _project(ctx, args.project)
    p = _resolve(root, args.path)
    if not p.is_file():
        raise CodeError(f"file not found: {args.path}")
    if p.stat().st_size > MAX_READ_BYTES:
        raise CodeError("file too large to read (> 200 KB)")
    text = p.read_text(encoding="utf-8", errors="replace")
    return ToolResult(ok=True, verified=True, data={"project": args.project, "path": args.path,
                                                    "lines": text.count("\n") + 1, "content": text[:20000],
                                                    "truncated": len(text) > 20000})


@register("search_code")
@_code_tool
def search_code(args: SearchCodeArgs, ctx: ToolContext) -> ToolResult:
    _, root = _project(ctx, args.project)
    q = args.query.lower()
    matches: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                if p.stat().st_size > MAX_READ_BYTES:
                    continue
                lines = p.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue  # binary or unreadable
            for i, line in enumerate(lines, 1):
                if q in line.lower():
                    matches.append({"file": p.relative_to(root).as_posix(), "line": i, "text": line.strip()[:200]})
                    if len(matches) >= 50:
                        return ToolResult(ok=True, verified=True, data={"matches": matches, "truncated": True})
    return ToolResult(ok=True, verified=True, data={"matches": matches, "truncated": False})


@register("git_status")
@_code_tool
def git_status(args: ProjectArgs, ctx: ToolContext) -> ToolResult:
    _, root = _project(ctx, args.project)
    changed = [ln[3:] for ln in _git(root, "status", "--porcelain").splitlines() if ln.strip()]
    return ToolResult(ok=True, verified=True, data={"project": args.project, "branch": _branch(root),
                                                    "changed": changed[:100]})


# ---------------------------------------------------------------- changes (always on ai/*)
def _ensure_ai_branch(ctx: ToolContext, project: str, root: Path, base: str) -> str:
    branch = _branch(root)
    if branch.startswith("ai/"):
        return branch
    if branch != base:
        raise CodeError(f"project is on '{branch}', expected the base branch '{base}'")
    if _git(root, "status", "--porcelain").strip():
        raise CodeError(f"'{base}' has uncommitted changes; commit or stash them first (the AI won't touch them)")
    new = "ai/" + time.strftime("%Y%m%d-%H%M%S")
    _git(root, "checkout", "-b", new)
    state = _state(ctx)
    state[project] = {"branch": new, "base": base, "base_head": _git(root, "rev-parse", base).strip()}
    _save_state(ctx, state)
    return new


def _find_span(text: str, old: str) -> tuple[int, int, bool]:
    """Where old_text is in text: exact match first, then a unique line-by-line match ignoring indentation and
    trailing spaces (small models often get whitespace slightly wrong). Raises if missing or ambiguous."""
    n = text.count(old)
    if n == 1:
        i = text.index(old)
        return i, i + len(old), False
    if n > 1:
        raise CodeError(f"old_text appears {n} times; include more context so it is unique")
    # Compare non-blank lines only: models often collapse the two blank lines between functions into one.
    want = [ln.strip() for ln in old.split("\n") if ln.strip()]
    if not want:
        raise CodeError("old_text not found in the file")
    lines = text.split("\n")
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln) + 1)
    nonblank = [(i, ln.strip()) for i, ln in enumerate(lines) if ln.strip()]
    hits = [k for k in range(len(nonblank) - len(want) + 1)
            if [s for _, s in nonblank[k:k + len(want)]] == want]
    if len(hits) != 1:
        raise CodeError("old_text not found in the file (copy it exactly from read_file)" if not hits
                        else f"old_text appears {len(hits)} times; include more context so it is unique")
    first, last = nonblank[hits[0]][0], nonblank[hits[0] + len(want) - 1][0]
    return starts[first], starts[last + 1] - 1, True  # whole lines, without the final line break


def _unescape_quotes(s: str) -> str:
    return s.replace('\\"', '"').replace("\\'", "'")


def _parses(src: str) -> bool:
    try:
        ast.parse(src)
    except SyntaxError:
        return False
    return True


def _reindent(new_text: str, before: str, a: int) -> str:
    """Re-indent replacement code to where it lands: the first line continues after the existing indentation
    (or starts the line), later lines get that indentation."""
    line_start = before.rfind("\n", 0, a) + 1
    lead = before[line_start:a]
    indent = lead if lead.strip() == "" else re.match(r"\s*", before[line_start:]).group(0)  # type: ignore[union-attr]
    lines = textwrap.dedent(new_text).split("\n")
    first = lines[0] if lead.strip() == "" else indent + lines[0]
    return "\n".join([first] + [indent + ln if ln.strip() else ln for ln in lines[1:]])


def _top_level_names(src: str) -> set[str]:
    return {n.name for n in ast.parse(src).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def _check_python_edit(before: str | None, after: str, allow_removing: bool) -> None:
    """Guardrails for small models: no syntax errors, and no silently deleted functions (G3: a new function
    replaced an existing one and broke its tests)."""
    try:
        new_names = _top_level_names(after)
    except SyntaxError as e:
        raise CodeError(f"edit not applied: the file would not be valid Python (line {e.lineno}: {e.msg})") from e
    if before is None or allow_removing:
        return
    try:
        removed = sorted(_top_level_names(before) - new_names)
    except SyntaxError:
        return  # the file was already broken: let the model fix it
    if removed:
        raise CodeError(f"edit not applied: it would delete {', '.join(removed)}. Keep existing code; to add "
                        "a new function use old_text '' (append)")


@register("edit_file")
@_code_tool
def edit_file(args: EditFileArgs, ctx: ToolContext) -> ToolResult:
    entry, root = _project(ctx, args.project)
    p = _resolve(root, args.path)
    before: str | None = None
    crlf = False
    if p.exists():
        if not p.is_file():
            raise CodeError(f"not a file: {args.path}")
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        before = raw.replace("\r\n", "\n")
    elif args.old_text:
        raise CodeError(f"file not found: {args.path}")
    new_text = args.new_text.replace("\r\n", "\n")
    old_text = args.old_text.replace("\r\n", "\n")
    if before is None:
        after = new_text
    elif old_text == "":  # append (e.g. a new function at the end of the module)
        body = before if before.endswith("\n") or not before else before + "\n"
        sep = "" if not body or new_text.startswith("\n") else ("\n\n" if p.suffix == ".py" else "\n")
        added = textwrap.dedent(new_text) if p.suffix == ".py" else new_text  # appended code is top level
        after = body + sep + (added if added.endswith("\n") else added + "\n")
    else:
        try:
            a, b, linewise = _find_span(before, old_text)
        except CodeError:
            if '\\"' not in old_text and "\\'" not in old_text:
                raise
            # Models sometimes JSON-escape quotes twice (G3 run 2/4: shout(...) + \"!\")
            old_text, new_text = (_unescape_quotes(old_text), _unescape_quotes(new_text))
            a, b, linewise = _find_span(before, old_text)
        if linewise and new_text.endswith("\n"):
            new_text = new_text[:-1]  # the matched lines keep their own line break
        after = before[:a] + new_text + before[b:]
        if p.suffix == ".py" and not _parses(after):
            fixed = before[:a] + _reindent(new_text, before, a) + before[b:]
            after = fixed if _parses(fixed) else after  # wrong indentation is the usual cause
    if p.suffix == ".py":
        _check_python_edit(before, after, args.allow_removing)
    branch = _ensure_ai_branch(ctx, args.project, root, entry.base_branch)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes((after.replace("\n", "\r\n") if crlf else after).encode("utf-8"))
    _git(root, "add", "--", p.relative_to(root).as_posix())
    _git(root, "commit", "-q", "-m", f"ai: edit {args.path}")  # checkpoint on the ai/* branch only
    stat = _git(root, "diff", "--stat", "HEAD~1", "HEAD").strip().splitlines()
    return ToolResult(ok=True, verified=p.read_bytes().decode("utf-8").replace("\r\n", "\n") == after,
                      data={"project": args.project, "branch": branch, "path": args.path,
                            "created": before is None, "appended": before is not None and args.old_text == "",
                            "stat": stat[-1] if stat else ""})


@register("run_tests")
@_code_tool
def run_tests(args: ProjectArgs, ctx: ToolContext) -> ToolResult:
    entry, root = _project(ctx, args.project)
    if not entry.test_cmd:
        raise CodeError("no test command configured for this project")
    t0 = time.monotonic()
    # No cached bytecode: an edit in the same second with the same size would otherwise run the OLD code
    # and report a false pass.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(entry.test_cmd, cwd=root, capture_output=True, text=True, encoding="utf-8",  # noqa: S603
                       errors="replace", timeout=ctx.cfg.tests_timeout_s, creationflags=NO_WINDOW, env=env)
    out = (r.stdout + "\n" + r.stderr).strip()
    return ToolResult(ok=True, verified=True,
                      data={"project": args.project, "passed": r.returncode == 0, "exit_code": r.returncode,
                            "duration_s": round(time.monotonic() - t0, 1), "output_tail": out[-3000:],
                            "branch": _branch(root)})


@register("git_diff")
@_code_tool
def git_diff(args: ProjectArgs, ctx: ToolContext) -> ToolResult:
    entry, root = _project(ctx, args.project)
    branch = _branch(root)
    if not branch.startswith("ai/"):
        return ToolResult(ok=True, verified=True, data={"project": args.project, "branch": branch,
                                                        "files": [], "diff": "", "note": "no AI changes"})
    base = _state(ctx).get(args.project, {}).get("base", entry.base_branch)
    files = _git(root, "diff", "--name-only", f"{base}...HEAD").split()
    stat = _git(root, "diff", "--shortstat", f"{base}...HEAD").strip()
    diff = _git(root, "diff", f"{base}...HEAD")
    return ToolResult(ok=True, verified=True, data={"project": args.project, "branch": branch, "base": base,
                                                    "files": files, "stat": stat, "diff": diff[:8000],
                                                    "truncated": len(diff) > 8000})


@register("revert_changes")
@_code_tool
def revert_changes(args: ProjectArgs, ctx: ToolContext) -> ToolResult:
    entry, root = _project(ctx, args.project)
    branch = _branch(root)
    if not branch.startswith("ai/"):
        return ToolResult(ok=True, verified=True, data={"project": args.project, "reverted": False,
                                                        "note": "nothing to revert"})
    st = _state(ctx).get(args.project, {})
    base = st.get("base", entry.base_branch)
    _git(root, "checkout", "-f", base)
    _git(root, "branch", "-D", branch)
    state = _state(ctx)
    state.pop(args.project, None)
    _save_state(ctx, state)
    head = _git(root, "rev-parse", base).strip()
    unchanged = st.get("base_head") in (None, head)
    clean = not _git(root, "status", "--porcelain").strip()
    return ToolResult(ok=True, verified=unchanged and clean and _branch(root) == base,
                      data={"project": args.project, "reverted": True, "branch_deleted": branch, "base": base,
                            "base_unchanged": unchanged})

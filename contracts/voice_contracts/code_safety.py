"""Risky-code check for AI edits (red-team I03/I07).

A comment planted in a file got the local model to add a download-and-run command and code that reads
secret keys; run_tests would then have executed it on PC2. Edits that add process, network, secret or
dynamic-code access, or that change build/test configuration, are held for the owner's approval on BOTH
PC1 (policy -> confirm) and PC2 (no matching approval hash -> deny) before they are written.

Best effort by design: a pattern list cannot prove code safe. It catches the common shapes; the ai/*
branch, the owner's fixed test command and revert_changes remain the backstop.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("runs other programs", re.compile(
        r"\bsubprocess\b|\bos\s*\.\s*(system|popen|exec\w*|spawn\w*|startfile|fork\w*|kill)\b|\bpty\b"
        r"|\bPopen\b|\bshell\s*=\s*True|child_process|\bexecSync\b|\bspawnSync\b|\bctypes\b"
        r"|\bStart-Process\b|\bInvoke-Expression\b|\biex\b|\bcmd(\.exe)?\s+/c\b|\bpowershell\b|\bbash\s+-c\b"
        r"|\|\s*(sh|bash|zsh|python\d?|pwsh)\b", re.I)),
    ("uses the network", re.compile(
        r"\b(import|from)\s+(socket|requests|websockets?)\b|\b(socket|requests|websockets?)\s*\.\s*\w"
        r"|\burllib\d?\b|\bhttp\.client\b|\bhttpx\b|\baiohttp\b|\bftplib\b"
        r"|\bsmtplib\b|\btelnetlib\b|\bparamiko\b|\bXMLHttpRequest\b|\bnew\s+WebSocket\b|\bfetch\s*\("
        r"|\bcurl\b|\bwget\b|\bInvoke-WebRequest\b|\biwr\b|\bInvoke-RestMethod\b|https?://", re.I)),
    ("reads secrets or environment", re.compile(
        r"\benviron\b|\bgetenv\b|\bputenv\b|process\.env|\bkeyring\b|\.ssh\b|\.aws\b|\bid_rsa\b"
        r"|\bcredentials\b|(^|[\s'\"/])\.env\b|\bAWS_|\bwin32cred\b", re.I)),
    ("runs hidden or generated code", re.compile(
        r"(?<!\.)\b(eval|exec|compile)\s*\(|\b__import__\b|\bimportlib\b|\bmarshal\b"
        r"|\bpickle\s*\.\s*loads?\b|\bb64decode\b|\bcodecs\s*\.\s*decode\b|\bgetattr\s*\(\s*(os|sys|builtins)\b"
        r"|\bbuiltins\b|\bnew\s+Function\s*\(", re.I)),
    ("deletes files outside the edit", re.compile(r"\bshutil\s*\.\s*rmtree\b|\brm\s+-rf?\b|\bRemove-Item\b", re.I)),
]

# Files that decide what runs during tests/builds: any change to them needs approval.
_CONFIG_NAMES = frozenset({
    "conftest.py", "setup.py", "setup.cfg", "pyproject.toml", "tox.ini", "pytest.ini", "noxfile.py",
    "package.json", "package-lock.json", "makefile", "dockerfile", ".npmrc", ".pypirc", "sitecustomize.py",
    "usercustomize.py", "vite.config.ts", "vite.config.js", "jest.config.js", "vitest.config.ts",
})
_CONFIG_PARTS = (".github", ".git", ".vscode", ".cursor", ".husky")


def risky_edit(path: str, new_text: str) -> list[str]:
    """Why this edit needs the owner's approval (empty list = no reason found)."""
    reasons: list[str] = []
    p = PurePosixPath(path.replace("\\", "/"))
    name = p.name.lower()
    if (name in _CONFIG_NAMES or name.startswith("requirements") or name.endswith((".pth", ".bat", ".cmd",
                                                                                     ".ps1", ".sh"))
            or any(part.lower() in _CONFIG_PARTS for part in p.parts)):
        reasons.append("changes build/test setup")
    for label, rule in _RULES:
        if rule.search(new_text):
            reasons.append(label)
    return reasons

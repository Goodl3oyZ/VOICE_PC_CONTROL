"""Alias normalisation (doc §3.1): fix spoken/transliterated names before planning.

"เปิดสปอติฟายหน่อย" -> "เปิด spotify หน่อย"
"""
from __future__ import annotations

import re


class AliasNormalizer:
    def __init__(self, aliases: dict[str, str], canonical: list[str] | None = None):
        table = {k.strip().lower(): v for k, v in aliases.items() if k.strip()}
        for name in canonical or []:
            table.setdefault(name.lower(), name)
        self._table = table
        keys = sorted(table, key=len, reverse=True)  # longest match first
        self._re = re.compile("|".join(re.escape(k) for k in keys), re.IGNORECASE) if keys else None

    def __call__(self, text: str) -> str:
        text = " ".join(text.split())
        if self._re is None:
            return text
        out = self._re.sub(lambda m: f" {self._table[m.group(0).lower()]} ", text)
        return " ".join(out.split())

    def lookup(self, word: str) -> str | None:
        return self._table.get(word.strip().lower())

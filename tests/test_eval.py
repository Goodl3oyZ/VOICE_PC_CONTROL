from __future__ import annotations

import pytest

from eval.run import cer, main, percentile


def test_cer_thai():
    assert cer("เปิดโครม", "เปิดโครม") == 0
    assert cer("เปิด โครม", "เปิดโครม") == 0  # whitespace ignored
    assert cer("abcd", "abxd") == pytest.approx(0.25)
    assert cer("", "") == 0


def test_percentile():
    assert percentile([1, 2, 3, 4, 100], 50) == 3
    assert percentile([], 95) == 0


def test_harness_runs_with_fake_llm_and_never_executes_dangerous(capsys):
    assert main(["--set", "dev"]) == 0
    out = capsys.readouterr().out
    assert "dangerous executed: 0" in out

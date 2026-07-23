"""Gate duro de VaR en risk_facilitator (revisión final 2026-07-06).

El guardrail determinista (VaR 2σ calibrado, regla #4) debe ser INVIOLABLE:
el LLM puede frenar un trade que pasó el VaR, pero JAMÁS aprobar uno que lo
reprobó. Antes era advisory: un facilitador persuadido soltaba el freno.
"""

import pytest

from src.brain.agents import risk as risk_mod

pytestmark = pytest.mark.unit


class _FakeLLM:
    def __init__(self, text):
        self._text = text

    def invoke(self, _msgs):
        class R:
            content = self._text

        R.content = self._text
        return R()


def _state(var_ok: bool):
    return {
        "risk_reports": [
            {"perspective": p, "size_usd": 100.0, "var_ok": var_ok, "assessment": "..."}
            for p in ("aggressive", "neutral", "conservative")
        ]
    }


def test_llm_yes_with_var_ok_approves(monkeypatch):
    monkeypatch.setattr(risk_mod, "get_llm", lambda role: _FakeLLM("APPROVED: YES — all good"))
    out = risk_mod.risk_facilitator(_state(var_ok=True))
    assert out["risk_approved"] is True


def test_llm_yes_with_var_fail_is_overruled(monkeypatch):
    # El LLM dice YES pero el VaR reprobó → el gate anula la aprobación.
    monkeypatch.setattr(risk_mod, "get_llm", lambda role: _FakeLLM("APPROVED: YES — trust me"))
    out = risk_mod.risk_facilitator(_state(var_ok=False))
    assert out["risk_approved"] is False
    assert "GATE" in out["risk_synthesis"]


def test_llm_no_stays_no_regardless(monkeypatch):
    monkeypatch.setattr(risk_mod, "get_llm", lambda role: _FakeLLM("APPROVED: NO — too risky"))
    out = risk_mod.risk_facilitator(_state(var_ok=True))
    assert out["risk_approved"] is False

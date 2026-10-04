"""The auto-close policy gate. Escalation is a designed success path.

    auto_close  IFF  confidence >= theta
                 AND all mandatory evidence types for this typology PRESENT
                 AND staleness_penalty == 0
                 AND citation_coverage == 1.0
                 AND no sanctions/PEP hit at any confidence
                 AND typology not in NEVER_AUTO_CLOSE
    else escalate_with_case_file

Six conditions, five deterministic, one a model score. Every condition is
evaluated and reported, even after one fails, so the console can show all six.
"""
from __future__ import annotations

from pydantic import BaseModel

from provenance.core.models import Decision, EvidenceType, Typology
from provenance.core.typologies import MANDATORY_EVIDENCE, NEVER_AUTO_CLOSE

DEFAULT_THETA = 0.90


class GateInput(BaseModel):
    typology: Typology
    confidence: float
    gathered_evidence: set[EvidenceType]
    staleness_penalty: float
    citation_coverage: float
    sanctions_or_pep_hit: bool
    theta: float = DEFAULT_THETA
    # Evidence types where the injection guard withheld untrusted content.
    withheld_evidence: set[EvidenceType] = set()


class GateCondition(BaseModel):
    name: str
    passed: bool
    detail: str


class GateResult(BaseModel):
    decision: Decision
    conditions: list[GateCondition]

    @property
    def passed(self) -> bool:
        return self.decision is Decision.AUTO_CLOSE

    @property
    def failed(self) -> list[GateCondition]:
        return [c for c in self.conditions if not c.passed]


def evaluate_gate(g: GateInput) -> GateResult:
    required = MANDATORY_EVIDENCE[g.typology]
    missing = [e.value for e in required if e not in g.gathered_evidence]
    withheld = [e.value for e in required if e in g.withheld_evidence]
    ev_detail = "all present"
    if missing:
        ev_detail = f"missing: {', '.join(missing)}"
    if withheld:
        ev_detail = (f"{ev_detail}; " if missing else "") + f"withheld by injection guard: {', '.join(withheld)}"
    conditions = [
        GateCondition(
            name="confidence",
            passed=g.confidence >= g.theta,
            detail=f"{g.confidence:.3f} vs theta {g.theta:.3f}",
        ),
        GateCondition(
            name="mandatory_evidence",
            passed=not missing and not withheld,
            detail=ev_detail,
        ),
        GateCondition(
            name="staleness",
            passed=g.staleness_penalty == 0,
            detail=f"penalty {g.staleness_penalty:.3f}",
        ),
        GateCondition(
            name="citation_coverage",
            passed=g.citation_coverage == 1.0,
            detail=f"coverage {g.citation_coverage:.3f}",
        ),
        GateCondition(
            name="no_sanctions_or_pep_hit",
            passed=not g.sanctions_or_pep_hit,
            detail="hit present" if g.sanctions_or_pep_hit else "no hit",
        ),
        GateCondition(
            name="typology_allows_auto_close",
            passed=g.typology not in NEVER_AUTO_CLOSE,
            detail=g.typology.value,
        ),
    ]
    decision = Decision.AUTO_CLOSE if all(c.passed for c in conditions) else Decision.ESCALATE
    return GateResult(decision=decision, conditions=conditions)

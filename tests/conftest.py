from datetime import UTC, datetime
from pathlib import Path

import pytest

from provenance.core.models import Claim, EvidenceType, SourceType

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def make_claim(
    assertion: str = "Account A received 14 transfers totalling 480,000 over 9 days.",
    evidence_type: EvidenceType = EvidenceType.TRANSACTIONS,
    source_type: SourceType = SourceType.BIGQUERY,
    as_of: datetime = datetime(2026, 9, 25, tzinfo=UTC),
    sla: int = 30,
    **kw,
) -> Claim:
    return Claim(
        assertion=assertion,
        evidence_type=evidence_type,
        source_type=source_type,
        source_uri=kw.pop("source_uri", f"bq://provenance.transactions?fingerprint={abs(hash(assertion))}"),
        source_as_of=as_of,
        retrieved_at=kw.pop("retrieved_at", NOW),
        freshness_sla_days=sla,
        extraction_method=kw.pop("extraction_method", "sql_template_v1"),
        produced_by_agent=kw.pop("produced_by_agent", "txn_analyst"),
        **kw,
    )


@pytest.fixture
def now() -> datetime:
    return NOW

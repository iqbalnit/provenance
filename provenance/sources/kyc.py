"""KYC facts from the structured customer profile (kill-list fallback for the
multimodal KYC agent). Profiles live at gs://<bucket>/kyc/<account>.json, or in
the demo bundle's customers.json.
"""
from __future__ import annotations

from datetime import datetime

from provenance.core.models import Claim, EvidenceType, SourceType
from provenance.core.typologies import FRESHNESS_SLA_DAYS

AGENT = "kyc_analyst"
FIELDS = {
    "occupation": "stated occupation is {}",
    "expected_monthly_volume": "declared expected monthly transaction volume is {}",
    "source_of_funds": "declared source of funds is {}",
    "country": "country of residence is {}",
}


def claims_from_profile(account_id: str, profile: dict, source_uri: str, retrieved_at: datetime) -> list[Claim]:
    reviewed = datetime.fromisoformat(profile["kyc_reviewed_at"])
    out = []
    for key, template in FIELDS.items():
        if key not in profile:
            continue
        value = profile[key]
        out.append(
            Claim(
                assertion=f"KYC profile for account {account_id} ({profile['name']}): {template.format(value)}.",
                evidence_type=EvidenceType.KYC,
                source_type=SourceType.KYC_DOC,
                source_uri=f"{source_uri}#/{key}",
                source_as_of=reviewed,
                retrieved_at=retrieved_at,
                freshness_sla_days=FRESHNESS_SLA_DAYS[EvidenceType.KYC],
                extraction_method="kyc_profile_json_v1",
                produced_by_agent=AGENT,
                verbatim_quote=str(value),
            )
        )
    return out

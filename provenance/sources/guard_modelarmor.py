"""Second-layer screen via Model Armor (sanitize_user_prompt).

Enabled when PROVENANCE_MODEL_ARMOR_TEMPLATE is set to a full template name:
projects/<p>/locations/<l>/templates/<t>. UNTESTED from the build container
(no GCP); verify the client surface against the installed google-cloud-modelarmor
on first use. Fails closed: any error withholds the text.
"""
from __future__ import annotations

import os

from provenance.core.guard import GuardResult


def enabled() -> bool:
    return bool(os.environ.get("PROVENANCE_MODEL_ARMOR_TEMPLATE"))


def screen(text: str) -> GuardResult:  # pragma: no cover - needs GCP
    try:
        from google.cloud import modelarmor_v1  # noqa: PLC0415

        template = os.environ["PROVENANCE_MODEL_ARMOR_TEMPLATE"]
        location = template.split("/")[3]
        client = modelarmor_v1.ModelArmorClient(
            client_options={"api_endpoint": f"modelarmor.{location}.rep.googleapis.com"})
        resp = client.sanitize_user_prompt(request=modelarmor_v1.SanitizeUserPromptRequest(
            name=template, user_prompt_data=modelarmor_v1.DataItem(text=text)))
        match = resp.sanitization_result.filter_match_state
        if match == modelarmor_v1.FilterMatchState.MATCH_FOUND:
            return GuardResult(False, ["model_armor_match"])
        return GuardResult(True)
    except Exception as e:  # fail closed
        return GuardResult(False, [f"model_armor_error:{type(e).__name__}"])

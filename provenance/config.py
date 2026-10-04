"""Runtime configuration from environment variables. See .env.example.

Values are read lazily: importing this module never fails, only asking for a
missing value does. Offline code paths (tests, --local runs) never ask.
"""
from __future__ import annotations

import os


class ConfigError(RuntimeError):
    pass


def _get(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if not v:
        raise ConfigError(f"Set {name} (see .env.example)")
    return v


def backend() -> str:
    """"vertex" (billed GCP project / credits) or "aistudio" (free Google AI Studio API key, no billing)."""
    return "vertex" if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in {"TRUE", "1"} else "aistudio"


def genai_client():
    """A google-genai client for whichever backend the environment selects. ADK reads the same variables."""
    from google import genai  # noqa: PLC0415

    if backend() == "vertex":
        return genai.Client(vertexai=True, project=project(), location=location())
    return genai.Client(api_key=_get("GOOGLE_API_KEY"))


def project() -> str:
    return _get("GOOGLE_CLOUD_PROJECT")


def location() -> str:
    """Vertex model endpoint location (not the Cloud Run region). Often "global" for newer models."""
    return _get("GOOGLE_CLOUD_LOCATION", "global")


def bq_dataset() -> str:
    return f"{project()}.{_get('PROVENANCE_BQ_DATASET', 'provenance')}"


def gcs_bucket() -> str:
    return _get("PROVENANCE_GCS_BUCKET")


def model(kind: str) -> str:
    """kind: 'flash' or 'pro'. Pinned IDs only; -latest aliases silently move eval arms."""
    var = f"PROVENANCE_MODEL_{kind.upper()}"
    v = _get(var)
    if v.endswith("-latest"):
        raise ConfigError(f"{var} must be a pinned model ID, not a -latest alias")
    return v

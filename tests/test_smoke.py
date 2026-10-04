import pytest

from provenance.smoke import SmokeFailure, backend_of, check_env, closest

GOOD = {"GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_CLOUD_LOCATION": "global", "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
        "PROVENANCE_MODEL_FLASH": "gemini-3-flash-001", "PROVENANCE_MODEL_PRO": "gemini-3-pro-001"}
FREE = {"GOOGLE_GENAI_USE_VERTEXAI": "FALSE", "GOOGLE_API_KEY": "k",
        "PROVENANCE_MODEL_FLASH": "gemini-3-flash-001", "PROVENANCE_MODEL_PRO": "gemini-3-pro-001"}


def test_aistudio_backend_needs_only_key_and_models():
    assert backend_of(FREE) == "aistudio" and check_env(FREE) == []
    with pytest.raises(SmokeFailure, match="GOOGLE_API_KEY"):
        check_env({**FREE, "GOOGLE_API_KEY": ""})
    assert backend_of({}) == "aistudio"


def test_env_ok():
    assert check_env(GOOD) == []


@pytest.mark.parametrize("patch,needle", [
    ({"PROVENANCE_MODEL_PRO": ""}, "missing env"),
    ({"GOOGLE_CLOUD_LOCATION": ""}, "missing env"),
    ({"PROVENANCE_MODEL_FLASH": "gemini-flash-latest"}, "alias"),
])
def test_env_failures(patch, needle):
    with pytest.raises(SmokeFailure, match=needle):
        check_env({**GOOD, **patch})


def test_env_warns_on_retiring_series():
    assert "retires" in check_env({**GOOD, "PROVENANCE_MODEL_FLASH": "gemini-2.5-flash"})[0]


def test_closest_model_names():
    listed = ["publishers/google/models/gemini-3-flash-001", "publishers/google/models/gemini-3-pro-001",
              "publishers/google/models/text-embedding-005"]
    assert closest("gemini-3-flash", listed)[0] == "gemini-3-flash-001"

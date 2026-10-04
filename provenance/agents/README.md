# Agents

`provenance_agent/` is the ADK graph (google-adk 2.10). `agent.py` has the diagram.

- `steps.py`: deterministic BaseAgents (case setup, evidence plan, KYC, adverse-media wrapper,
  verifier + gate, finalise). Auditability demands these be code.
- `tools.py`: function tools. They write claims themselves; the model only chooses what to look up
  and cannot author a claim. `query_transactions` refuses accounts outside the alert's scope.
- `prompts.py`: instruction providers.
- `offline.py`: scripted stand-in models for `PROVENANCE_MODE=offline`, used by CI and as the
  fallback demo. Never used for reported numbers.

Before real Gemini runs:
1. Pin `PROVENANCE_MODEL_FLASH` / `_PRO`.
2. Run `PROVENANCE_MODE=gemini uv run python -m provenance.service.run alt_demo_hero` and check that
   the typologist's and disposition's JSON validate against their output schemas.
3. Confirm `media_search` returns `grounding_metadata` on its events. If it arrives on a different
   event or field in this ADK version, fix `steps.AdverseMedia` (the offline test pins the contract).
4. Add Model Armor on the adverse-media text before it becomes claims (the `safety-plugins` sample).

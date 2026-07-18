# Strategy Promotion

All 97 imported strategies begin as hypotheses. JSON formulas and signal text are metadata and are never passed to `eval`, compiled, or used to generate runtime code.

The lifecycle is `DRAFT → VALIDATED → BACKTESTED → SCORED → APPROVED_FOR_RECOMMENDATION → SHADOW_VALIDATED → BUILDER_READY`. Registration and semantic validation do not require a score. Historical experiments may run from `VALIDATED` onward. Approval requires exact tested Python semantics, complete data, validated features, protocol backtests, score at least 65, no hard rejection, stable parameters, positive high-cost results, multiple-testing and protected holdout evidence, capacity, long-only compatibility, an exact enabled runtime definition, and deterministic golden vectors. SHADOW evidence is required only for `BUILDER_READY`; an approved research candidate without it remains unavailable to Portfolio Builder.

Use the trusted command only after evidence exists:

```powershell
python manage.py promote_research_strategy RESEARCH_ID `
  apps.research.implementations.wave0.FixedWeightResearch `
  FIXED_WEIGHT_REBALANCE `
  --actor operator-name `
  --evidence-json '{"golden_vector_passed":true,"high_cost_passed":true,"multiple_testing_passed":true,"shadow_validated":true}'
```

The command does not create a new runtime definition and cannot approve selectors, allocators, overlays, long-short, pair/basket, or inexact mappings as ordinary single-asset plugins. Runtime definitions and instances remain subject to existing enabled flags and SHADOW/PAPER-only controls. Newly constructed instances remain disabled SHADOW.

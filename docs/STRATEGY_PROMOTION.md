# Strategy implementation and promotion

All 97 active catalogue IDs are present in `services/strategy_registry.py`. Each entry declares an importable Python object, role, scope-aware engine, data/features, explicit parameter names and bounded budget, compatible profiles, fallback behavior, implementation version/hash, and optional runtime mapping. Registry validation fails bundle activation or tests when an ID, path, role, or parameter schema differs. JSON formula and signal text are retained as documentation and are never evaluated, compiled, or used to generate code.

Roles are deliberately separated. Selectors, income, allocators, events, and overlays contribute research scores; they do not manufacture single-stock strategy instances. Pair/basket models are bounded research-only screens and cannot create an order. Only exact long-only execution semantics have runtime definitions, and those recommendation-created definitions are hidden from the manual selector.

The lifecycle is:

```text
DRAFT → VALIDATED → BACKTESTED → SCORED → APPROVED_FOR_RECOMMENDATION
      → SHADOW_VALIDATED → BUILDER_READY
```

Promotion requires tested Python semantics, validated point-in-time data/features, the active protocol, positive high-cost performance, capacity, stability, multiple-testing evidence, protected holdout, exact enabled runtime mapping, deterministic golden vectors, and an actor/evidence record. SHADOW evidence is never fabricated by bootstrap.

Example for the baseline mapping:

```powershell
python manage.py promote_research_strategy BH_001 `
  apps.research.implementations.baseline.BH_001 `
  FIXED_WEIGHT_REBALANCE `
  --implementation-version full-universe-v1 `
  --actor operator-name `
  --evidence-json '{"golden_vector_passed":true,"high_cost_passed":true,"multiple_testing_passed":true,"shadow_validated":true}'
```

Promotion cannot bypass SHADOW/PAPER-only startup guards, create LIVE instances, or turn selectors/pairs into inexact runtime plugins. Applied Builder instances remain disabled until the existing operator review workflow enables an eligible PAPER instance.

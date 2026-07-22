# Adding a strategy plugin

Strategy plugins convert final, versioned market facts into the common `StrategyTarget` contract. They never import OMS, the Gateway client, or broker APIs. The platform owns target aggregation, rebalancing, sizing, risk, order construction, OMS, fills, ledgers, and reconciliation.

## Contract

Subclass `StrategyPlugin` from `apps/strategies/plugins/base.py` and declare:

- a stable uppercase `key`, display name, and description;
- supported asset types, directions, and timeframes;
- JSON Schema parameters and safe defaults;
- required bars/fields, parameterized indicators, and warm-up bars;
- `evaluate(context)`, returning `StrategyDecision`;
- optionally `build_target`; the base implementation emits the standard weight/flat target.

The context contains the exact instance and immutable version, canonical instrument, final bar, current and previous indicators, isolated strategy state, attributed position, active attributed orders, portfolio/session state, and triggering-event metadata. A decision may be `ENTER_LONG`, `EXIT_LONG`, `ENTER_SHORT`, `EXIT_SHORT`, `SET_TARGET`, `HOLD`, or `NO_ACTION`.

Use [template.py](../apps/strategies/plugins/template.py) as the starting implementation and [strategy_plugin_fixture.py](../tests/strategy_plugin_fixture.py) to construct unit-test contexts.

## Registration

1. Put the plugin in `apps/strategies/plugins/` or another importable module.
2. Add built-ins to `plugins/registry.py`. For an external plugin, insert a `StrategyDefinition` whose `plugin_path` is the fully qualified class path.
3. Store the plugin schema and supported metadata in the definition migration.
4. Create an instance through `POST /api/v1/strategy-instances/`. This validates the schema, resolves its canonical instrument/IBKR contract, creates immutable version 1, and publishes shared input requirements.
5. Enable only after qualification and warm-up. New instances remain `SHADOW` by default; `PAPER` is explicit and `LIVE` is rejected.

## Indicator identity and reuse

Declare indicator parameters precisely. The registry de-duplicates by:

```text
instrument + timeframe + indicator name + canonical parameters hash
```

Do not name indicators after a strategy instance. Two RSI strategies with the same instrument, timeframe, and window intentionally share one calculation even when their thresholds differ.

## Required tests

- JSON Schema and semantic validation, including invalid boundaries;
- warm-up and missing-input behavior;
- each supported direction and state transition;
- deterministic target construction and replay idempotency;
- ticker portability using the same plugin on two instruments;
- strategy portability beside another plugin on one instrument;
- plugin exception isolation;
- netting/attribution when targets oppose.

Run:

```bash
python -m pytest -q
```

A plugin is not complete if rebalancing, risk, OMS, Gateway, ledger, reconciliation, or the common execution timeline must be modified specifically for it.

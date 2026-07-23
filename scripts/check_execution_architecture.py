"""Static ownership checks for the documented automatic execution pipeline."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "ARCHITECTURE.md"

PIPELINE = [
    "Market provider",
    "market.raw.v1",
    "Flink normalization",
    "Flink bars and indicators",
    "Kafka derived-market topics",
    "Backend market persistence",
    "StrategyEvaluationJob",
    "Strategy evaluation worker",
    "StrategyTarget",
    "PortfolioTargetSnapshot",
    "RebalanceRun",
    "OrderIntent",
    "Intent execution worker",
    "risk checks",
    "OMS Order",
    "durable BrokerCommand",
    "Gateway",
    "IBKR paper account",
    "broker events",
    "fills and reconciliation",
]

REQUIRED_STATEMENTS = [
    "Flink owns market-derived computations only.",
    "PostgreSQL owns financial workflow state.",
    "Kafka transports events but is not the financial source of truth.",
    "Strategy plugins never submit broker orders.",
    "The Gateway never decides portfolio allocation or risk.",
    "All automatic orders pass through one common intent execution service.",
]

REQUIRED_LEGACY_PATHS = [
    "Backend/apps/market_streams/models.py",
    "Backend/apps/market_streams/services.py",
    "Backend/apps/strategies/views.py",
    "Backend/apps/rebalancing/services.py",
    "Backend/apps/allocation/services.py",
    "Backend/apps/core/views.py",
]

FORBIDDEN_PLUGIN_IMPORTS = (
    "apps.oms",
    "apps.risk",
    "apps.broker_gateway",
    "gateway_service",
    "IB_gateway",
    "ib_async",
    "broker",
)

BACKEND_PLACE_ORDER_ALLOWLIST = {
    "Backend/apps/execution/dispatch.py",
    "apps/execution/dispatch.py",
}


def fail(message: str) -> None:
    raise SystemExit(f"architecture check failed: {message}")


def pipeline_block(document: str) -> str:
    start_marker = "<!-- automatic-pipeline:start -->"
    end_marker = "<!-- automatic-pipeline:end -->"
    if document.count(start_marker) != 1 or document.count(end_marker) != 1:
        fail("exactly one marked automatic pipeline is required")
    return document.split(start_marker, 1)[1].split(end_marker, 1)[0]


def check_document() -> None:
    if not DOCUMENT.is_file():
        fail(f"{DOCUMENT.relative_to(ROOT)} is missing")
    document = DOCUMENT.read_text(encoding="utf-8")
    block = pipeline_block(document)
    cursor = -1
    for stage in PIPELINE:
        if block.count(stage) != 1:
            fail(f"pipeline stage must appear exactly once: {stage}")
        position = block.find(stage, cursor + 1)
        if position < 0:
            fail(f"pipeline stage is missing or out of order: {stage}")
        cursor = position
    for statement in REQUIRED_STATEMENTS:
        if statement not in document:
            fail(f"required ownership statement is missing: {statement}")
    for path in REQUIRED_LEGACY_PATHS:
        if path not in document:
            fail(f"legacy candidate is not documented: {path}")
    for mode in ("`OBSERVE`", "`SHADOW`", "`PAPER`"):
        if mode not in document:
            fail(f"execution mode is not documented: {mode}")


def import_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def check_plugin_isolation() -> None:
    plugin_roots = [
        ROOT / "Backend" / "apps" / "strategies" / "plugins",
        ROOT / "apps" / "strategies" / "plugins",
    ]
    for plugin_root in plugin_roots:
        if not plugin_root.is_dir():
            continue
        for path in plugin_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for imported in import_names(tree):
                if any(imported == prefix or imported.startswith(prefix + ".") for prefix in FORBIDDEN_PLUGIN_IMPORTS):
                    fail(
                        f"strategy plugin imports execution or broker layer: "
                        f"{path.relative_to(ROOT).as_posix()} -> {imported}"
                    )


def check_backend_submission_sites() -> None:
    backend_roots = [ROOT / "Backend" / "apps", ROOT / "apps"]
    call_sites: set[str] = set()
    for backend_root in backend_roots:
        if not backend_root.is_dir():
            continue
        for path in backend_root.rglob("*.py"):
            if "migrations" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"place_order", "modify_order", "cancel_order"}
                for node in ast.walk(tree)
            ):
                call_sites.add(path.relative_to(ROOT).as_posix())
    unexpected = call_sites - BACKEND_PLACE_ORDER_ALLOWLIST
    if unexpected:
        fail(f"undocumented Backend order-command call site(s): {sorted(unexpected)}")
    if call_sites and not call_sites <= BACKEND_PLACE_ORDER_ALLOWLIST:
        fail(f"Backend place_order allowlist mismatch: {sorted(call_sites)}")


def check_market_persistence_isolation() -> None:
    service_paths = [
        ROOT / "Backend" / "apps" / "market_streams" / "services.py",
        ROOT / "apps" / "market_streams" / "services.py",
    ]
    found = False
    for path in service_paths:
        if not path.is_file():
            continue
        found = True
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        forbidden_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"evaluate_instance", "get_plugin"}
        }
        if forbidden_calls:
            fail(
                "market persistence may not execute strategy plugins: "
                f"{path.relative_to(ROOT).as_posix()} -> {sorted(forbidden_calls)}"
            )
        if "ensure_strategy_evaluation_job" not in source:
            fail(
                "market persistence must create durable strategy evaluation jobs: "
                f"{path.relative_to(ROOT).as_posix()}"
            )
        for required in ("requirement_identity_hash", 'mode=="LIVE"'):
            if required not in source:
                fail(
                    "market persistence is missing deterministic identity/mode protection: "
                    f"{path.relative_to(ROOT).as_posix()} -> {required}"
                )
        if "parameters_hash" in source:
            fail(
                "market persistence still contains parameter-only readiness matching: "
                f"{path.relative_to(ROOT).as_posix()}"
            )
    backend_checkout = (ROOT / "Backend" / "manage.py").is_file() or (ROOT / "manage.py").is_file()
    if backend_checkout and not found:
        fail("market persistence service is missing")


def check_streaming_restart_contract() -> None:
    normalizer = ROOT / "streaming" / "flink" / "jobs" / "market_normalization.py"
    if not normalizer.is_file():
        return
    source = normalizer.read_text(encoding="utf-8")
    for required in (
        "UNKNOWN_CONID_BUFFER_TIMEOUT_MS",
        "UNKNOWN_CONID_BUFFER_MAX_EVENTS",
        "DEDUPLICATION_STATE_TTL_SECONDS",
        "StateTtlConfig",
        "KeyedCoProcessFunction",
    ):
        if required not in source:
            fail(f"streaming restart contract is missing: {required}")
    indicator = (
        ROOT / "streaming" / "flink" / "jobs" / "indicator_computation.py"
    ).read_text(encoding="utf-8")
    if "requirement_identity_hash" not in indicator or "parameters_hash" in indicator:
        fail("indicator computation must use the full requirement identity")


def main() -> None:
    check_document()
    check_plugin_isolation()
    check_backend_submission_sites()
    check_market_persistence_isolation()
    check_streaming_restart_contract()
    print("automatic execution architecture checks passed")


if __name__ == "__main__":
    main()

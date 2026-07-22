from django.core.management.base import BaseCommand, CommandError

from apps.market_data.mapping import verify_finnhub_mapping

from ...services.strategy_registry import synchronize_strategy_registry
from ...services.universe_pipeline import (
    active_recommendation_universe,
    map_universe_batch,
    qualify_universe_batch,
)


class Command(BaseCommand):
    help = "Idempotently bootstrap the complete 500-stock/97-strategy recommendation system"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=25)
        parser.add_argument("--skip-external", action="store_true", help="Skip IBKR qualification and Finnhub verification")

    def handle(self, *args, **options):
        try:
            universe = active_recommendation_universe(require_complete=True)
            registry = synchronize_strategy_registry(universe.dataset_version)
            batch_size = max(1, min(100, options["batch_size"]))
            mapped = 0
            for offset in range(0, 500, batch_size):
                mapped += map_universe_batch(offset=offset, batch_size=batch_size)["processed"]
            qualified = verified = 0; failures = []
            if not options["skip_external"]:
                for offset in range(0, 500, batch_size):
                    result = qualify_universe_batch(offset=offset, batch_size=batch_size)
                    qualified += result["qualified"]; failures.extend(result["failed"])
                for member in universe.members.filter(active=True, instrument__isnull=False).select_related("instrument__broker_contract"):
                    if not hasattr(member.instrument, "broker_contract"):
                        continue
                    try:
                        mapping = verify_finnhub_mapping(member.instrument)
                        verified += int(mapping.status == "VERIFIED")
                        if mapping.status != "VERIFIED":
                            failures.append({"symbol":member.source_symbol,"stage":"FINNHUB","error":mapping.last_error})
                    except Exception as exc:
                        failures.append({"symbol":member.source_symbol,"stage":"FINNHUB","error":str(exc)[:500]})
            report = {
                "universe": universe.key, "active_members": universe.members.filter(active=True).count(),
                "mapped_processed": mapped, "strategies_registered": registry["registered"],
                "ibkr_qualified": qualified, "finnhub_verified": verified, "external_failures": failures[:100],
                "safety": {"live_trading": False, "generation_creates_orders": False, "strategy_instances_enabled": False},
            }
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(str(report)))

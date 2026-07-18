import json

from django.core.management.base import BaseCommand, CommandError

from apps.research.services.mvp import run_mvp_pipeline


class Command(BaseCommand):
    help="Idempotently prepare and validate the controlled 5-stock x 5-strategy recommendation MVP"

    def handle(self,*args,**options):
        try:result=run_mvp_pipeline()
        except ValueError as exc:raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Recommendation MVP: dataset {result['dataset']}, protocol {result['protocol']}, "
            f"{result['experiment_groups']} experiment groups, {result['scores']['candidate_scores_updated']} scores"
        ))
        if result["missing_ibkr_contracts"]:
            self.stdout.write(self.style.WARNING(
                "Missing exact IBKR contracts: "+", ".join(result["missing_ibkr_contracts"])
            ))
        headers=["Stock","Fixed","SMA","RSI","Donchian","Vol-Target"]
        self.stdout.write(" | ".join(headers))
        self.stdout.write("-"*96)
        for stock in result["matrix"]["stocks"]:
            cells=[]
            for cell in stock["strategies"]:
                value=cell["status"]
                if cell["score"] is not None:value+=f" {cell['score']:.1f}"
                if cell["blockers"]:value+=f" ({cell['blockers'][0]})"
                cells.append(value)
            self.stdout.write(" | ".join([stock["symbol"],*cells]))
        self.stdout.write(json.dumps({
            "mapping_reports":result["mapping_reports"],"data_reports":result["data_reports"],
            "experiments_created":result["experiments_created"],"experiments_reused":result["experiments_reused"],
        },default=str,sort_keys=True))

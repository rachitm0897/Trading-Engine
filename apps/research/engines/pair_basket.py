from .base import PairBasketResearchStrategy


class ResearchOnlyPairBasket(PairBasketResearchStrategy):
    def targets(self, panel, parameters, context):
        raise RuntimeError("Pair/basket strategies are research-only and cannot emit runtime StrategyInstance targets")

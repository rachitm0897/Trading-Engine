from .base import SleeveAllocator


class ConstrainedAllocator(SleeveAllocator):
    def allocate(self, returns, holdings, constraints, parameters):
        from ..services.optimizer import optimize_sleeves
        return optimize_sleeves(returns, constraints=constraints, current_weights=holdings)

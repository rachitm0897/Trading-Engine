from .base import EventResearchStrategy


class AvailableEventStrategy(EventResearchStrategy):
    def signals(self, events, point_in_time_bars, parameters, context):
        cutoff = parameters["decision_timestamp"]
        return [event for event in events if event.available_timestamp <= cutoff]

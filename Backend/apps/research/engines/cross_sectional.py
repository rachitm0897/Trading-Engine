from .base import CrossSectionalSelector


class RankedSelector(CrossSectionalSelector):
    def rank(self, panel, parameters, context):
        key = parameters["score_key"]
        reverse = bool(parameters.get("descending", True))
        return sorted(panel, key=lambda item: (item.get(key) is not None, item.get(key, 0)), reverse=reverse)

from .base import ExposureOverlay


class BoundedScalarOverlay(ExposureOverlay):
    def apply(self, base_weights, risk_state, parameters):
        scalar = max(float(parameters.get("minimum", 0)), min(float(parameters.get("maximum", 1)), float(risk_state.get("exposure_scalar", 1))))
        return [float(value) * scalar for value in base_weights]

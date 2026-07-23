from apps.core.views import method_guard, response

from .readiness import collect_execution_readiness


def readiness(request):
    invalid = method_guard(request, "GET")
    if invalid:
        return invalid
    try:
        result = collect_execution_readiness()
        return response(result, status=200 if result["ready"] else 503)
    except Exception as exc:
        return response(
            status=503,
            error={
                "code": "EXECUTION_READINESS_FAILED",
                "message": str(exc),
                "details": {},
            },
        )

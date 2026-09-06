"""GET /health - liveness check.

Deliberately unauthenticated and free of dependency calls, so it stays cheap
and works as a smoke test that the API is deployed and reachable.
"""

import os
from typing import Any

from models.journal_entry import utc_now_iso
from utils import api_response


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return api_response.success(
        {
            "status": "healthy",
            "environment": os.environ.get("ENVIRONMENT", "unknown"),
            "timestamp": utc_now_iso(),
        }
    )

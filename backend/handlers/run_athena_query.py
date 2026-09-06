"""GET /analytics/athena?query=<name> - run a named analytics query."""

from typing import Any

from services import athena_service
from services.athena_service import AthenaError, AthenaTimeoutError
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id, query_params

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    query_name = query_params(event).get("query")
    if not query_name:
        available = ", ".join(athena_service.available_queries())
        return api_response.validation_error(f"Query name is required. Available: {available}")

    try:
        # run_query rejects any name that is not in the allow-list, so no
        # caller-supplied SQL ever reaches Athena.
        result = athena_service.run_query(query_name, user_id)
    except ValueError:
        available = ", ".join(athena_service.available_queries())
        return api_response.validation_error(f"Unknown query. Available: {available}")
    except AthenaTimeoutError as exc:
        return api_response.error(api_response.TIMEOUT, str(exc), 504)
    except AthenaError as exc:
        return api_response.error(api_response.EXTERNAL_API_ERROR, str(exc), 502)
    except Exception:
        logger.exception("Athena query %s failed", query_name)
        return api_response.internal_error()

    return api_response.success({"result": result})

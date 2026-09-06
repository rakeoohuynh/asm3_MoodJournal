"""GET /dashboard - aggregated mood statistics for the charts."""

from typing import Any

from services import analytics_service
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id, query_params
from utils.validation import ValidationError, validate_period

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    try:
        days = validate_period(query_params(event).get("period"))
    except ValidationError as exc:
        return api_response.validation_error(str(exc))

    try:
        dashboard = analytics_service.build_dashboard(user_id, days)
    except Exception:
        logger.exception("Failed to build dashboard for user %s", user_id)
        return api_response.internal_error()

    return api_response.success({"dashboard": dashboard})

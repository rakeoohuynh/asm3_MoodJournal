"""POST /reflections - generate an AI reflection for a period."""

from typing import Any

from services import reflection_service
from services.gemini_service import GeminiError
from services.reflection_service import NoEntriesError
from utils import api_response
from utils.logging_config import get_logger
from utils.request_context import MissingIdentityError, get_user_id
from utils.validation import ValidationError, validate_period

logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        user_id = get_user_id(event)
    except MissingIdentityError:
        return api_response.unauthorized()

    try:
        body = api_response.parse_body(event)
        days = validate_period(body.get("period"))
    except (ValueError, ValidationError) as exc:
        return api_response.validation_error(str(exc))

    try:
        reflection = reflection_service.create_reflection(
            user_id=user_id, days=days, generated_by="manual"
        )
    except NoEntriesError:
        return api_response.validation_error(
            "There are no entries in this period to reflect on."
        )
    except GeminiError as exc:
        # The exception text can carry Gemini's raw error body, which is useful
        # in logs but should not be echoed back to the browser.
        logger.warning("Reflection generation failed for user %s: %s", user_id, exc)
        return api_response.error(
            api_response.EXTERNAL_API_ERROR,
            "Could not generate a reflection at this time. Please try again later.",
            502,
        )
    except Exception:
        logger.exception("Failed to create reflection for user %s", user_id)
        return api_response.internal_error()

    return api_response.success({"reflection": reflection.to_api()}, status_code=201)

"""Unified API error format.

Every error response has the shape::

    {"error": {"code": "validation_error", "message": "...", "details": {...}}}

Unexpected exceptions are logged server-side (type and request path only) and returned
as a generic 500 without stack traces or internal paths.
"""
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("worldweaver.api")


class Conflict(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Конфлікт версій."
    default_code = "conflict"


class ServiceUnavailable(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Сервіс тимчасово недоступний."
    default_code = "service_unavailable"


def _first_message(detail):
    if isinstance(detail, list) and detail:
        return _first_message(detail[0])
    if isinstance(detail, dict) and detail:
        key, value = next(iter(detail.items()))
        msg = _first_message(value)
        return msg if key in ("non_field_errors", "detail") else f"{key}: {msg}"
    return str(detail)


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        exc = exceptions.ValidationError(detail=detail)
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound("Обʼєкт не знайдено.")
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        request = context.get("request")
        logger.exception("Unhandled API error %s on %s", type(exc).__name__, getattr(request, "path", "?"))
        return Response(
            {"error": {"code": "server_error", "message": "Внутрішня помилка сервера.", "details": None}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, exceptions.ValidationError):
        code = "validation_error"
        details = response.data
        message = _first_message(details)
    else:
        codes = exc.get_codes() if isinstance(exc, exceptions.APIException) else "error"
        code = codes if isinstance(codes, str) else "error"
        data = response.data
        message = str(data.get("detail", data)) if isinstance(data, dict) else str(data)
        details = None
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response


def json_404(request, exception=None):
    return JsonResponse({"error": {"code": "not_found", "message": "Не знайдено.", "details": None}}, status=404)


def json_500(request):
    return JsonResponse(
        {"error": {"code": "server_error", "message": "Внутрішня помилка сервера.", "details": None}}, status=500
    )

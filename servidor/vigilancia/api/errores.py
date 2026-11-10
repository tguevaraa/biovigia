"""Traducción de errores al formato del contrato v1: {"error", "campo", "detalle"}."""
from __future__ import annotations

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from ..servicios.errores import ErrorDominio


def _primer_error(detalle, ruta: str = "") -> tuple[str | None, str]:
    """Extrae el primer campo y mensaje de un ``ValidationError`` de DRF (anidado o no)."""
    if isinstance(detalle, dict):
        for campo, valor in detalle.items():
            nombre = f"{ruta}.{campo}" if ruta else str(campo)
            if campo == "non_field_errors":
                nombre = ruta or None
            return _primer_error(valor, nombre or "")
    if isinstance(detalle, list) and detalle:
        return _primer_error(detalle[0], ruta)
    return (ruta or None), str(detalle)


def respuesta_error(codigo: str, detalle: str, estado: int, campo: str | None = None):
    cuerpo = {"error": codigo, "detalle": detalle}
    if campo:
        cuerpo = {"error": codigo, "campo": campo, "detalle": detalle}
    return Response(cuerpo, status=estado)


def manejador_de_errores(exc, context):
    if isinstance(exc, ErrorDominio):
        return respuesta_error(exc.codigo, exc.detalle, exc.estado_http, exc.campo)
    if isinstance(exc, exceptions.ValidationError):
        campo, mensaje = _primer_error(exc.detail)
        return respuesta_error("validacion", mensaje, status.HTTP_422_UNPROCESSABLE_ENTITY, campo)
    if isinstance(exc, exceptions.ParseError):
        return respuesta_error("validacion", "El cuerpo no es JSON válido.",
                               status.HTTP_422_UNPROCESSABLE_ENTITY)

    respuesta = exception_handler(exc, context)
    if respuesta is None:
        return None
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        respuesta.data = {"error": "no_autenticado", "detalle": str(exc.detail)}
    elif isinstance(exc, exceptions.PermissionDenied):
        respuesta.data = {"error": "acceso_denegado",
                          "detalle": "Tu rol no tiene acceso a este recurso."}
    elif isinstance(exc, exceptions.NotFound):
        respuesta.data = {"error": "no_encontrado", "detalle": str(exc.detail)}
    elif isinstance(exc, exceptions.APIException):
        respuesta.data = {"error": exc.default_code, "detalle": str(exc.detail)}
    return respuesta

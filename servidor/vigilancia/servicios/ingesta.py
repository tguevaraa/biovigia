"""Ingesta de eventos de descarte (M4: veredicto, evidencia y estado).

Implementa la sección 3 del contrato v1, «Qué hace el servidor al recibirlo».
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from ..models import (
    VEREDICTO_POR_TIPO,
    Box,
    CambioEstado,
    EstadoRecipiente,
    Evento,
    Recipiente,
    TipoRecipiente,
    Veredicto,
)
from .errores import ErrorValidacion
from .tiempo import turno_de

log = logging.getLogger("biovigia.ingesta")


@dataclass
class ResultadoIngesta:
    evento: Evento
    creado: bool
    estado_recipiente: str
    evidencia_guardada: bool


def decodificar_evidencia(b64: str) -> bytes:
    """Valida que la evidencia sea un JPEG real de hasta 2 MB. Devuelve los bytes."""
    if "," in b64[:64] and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]  # admite «data:image/jpeg;base64,...»
    try:
        crudo = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ErrorValidacion("no es base64 válido", campo="evidencia_jpeg_b64") from exc
    if len(crudo) > settings.EVIDENCIA_MAX_BYTES:
        raise ErrorValidacion("supera el máximo de 2 MB", campo="evidencia_jpeg_b64")
    try:
        with Image.open(io.BytesIO(crudo)) as img:
            formato = img.format
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ErrorValidacion("no es una imagen válida", campo="evidencia_jpeg_b64") from exc
    if formato != "JPEG":
        raise ErrorValidacion("debe ser JPEG", campo="evidencia_jpeg_b64")
    return crudo


def _resultado(evento: Evento, creado: bool) -> ResultadoIngesta:
    evento.recipiente.refresh_from_db(fields=["estado"])
    return ResultadoIngesta(
        evento=evento,
        creado=creado,
        estado_recipiente=evento.recipiente.estado,
        evidencia_guardada=evento.evidencia_disponible,
    )


def registrar_evento(datos: dict[str, Any]) -> ResultadoIngesta:
    """Registra un descarte. Idempotente por ``id_externo`` (contrato v1, regla 2).

    ``datos`` llega ya validado en forma por el serializador; aquí se aplican las reglas.
    """
    existente = (
        Evento.objects.select_related("recipiente").filter(id_externo=datos["id_externo"]).first()
    )
    if existente is not None:
        return _resultado(existente, creado=False)

    ocurrido_en = datos["ocurrido_en"]
    margen = timedelta(seconds=settings.BIOVIGIA_DESFASE_RELOJ_S)
    if ocurrido_en > timezone.now() + margen:
        raise ErrorValidacion("no puede ser una fecha futura", campo="ocurrido_en")

    try:
        box = Box.objects.get(codigo=datos["box"], activo=True)
    except Box.DoesNotExist as exc:
        raise ErrorValidacion("box no registrado o inactivo", campo="box") from exc

    tipo = TipoRecipiente(datos["recipiente"])
    veredicto = VEREDICTO_POR_TIPO[tipo]  # el servidor manda sobre el veredicto
    reportado = datos["veredicto"]
    if reportado != veredicto:
        log.warning("Discrepancia de veredicto en %s: visión=%s servidor=%s",
                    datos["id_externo"], reportado, veredicto)

    evidencia = None
    if datos.get("evidencia_jpeg_b64"):
        evidencia = decodificar_evidencia(datos["evidencia_jpeg_b64"])

    confianza = Decimal(str(datos["confianza"])).quantize(Decimal("0.001"), ROUND_HALF_UP)

    evento: Evento | None = None
    try:
        with transaction.atomic():
            recipiente, _ = Recipiente.objects.select_for_update().get_or_create(
                box=box, tipo=tipo
            )
            evento = Evento(
                id_externo=datos["id_externo"],
                recipiente=recipiente,
                veredicto=veredicto,
                veredicto_reportado=reportado,
                confianza=confianza,
                ocurrido_en=ocurrido_en,
                turno=turno_de(ocurrido_en),
                modelo=datos["modelo"],
                rasgos=datos.get("rasgos") or {},
            )
            if evidencia is not None:
                nombre = f"{datos['id_externo'].replace(':', '').replace('.', '_')}.jpg"
                evento.evidencia.save(nombre, ContentFile(evidencia), save=False)
            evento.save()

            if (veredicto == Veredicto.NO_CONFORME
                    and recipiente.estado == EstadoRecipiente.NORMAL):
                recipiente.estado = EstadoRecipiente.CONTAMINADO
                recipiente.contaminado_desde = ocurrido_en
                recipiente.evento_causa = evento
                recipiente.save(update_fields=["estado", "contaminado_desde", "evento_causa"])
                CambioEstado.objects.create(
                    recipiente=recipiente,
                    estado_anterior=EstadoRecipiente.NORMAL,
                    estado_nuevo=EstadoRecipiente.CONTAMINADO,
                    ocurrido_en=ocurrido_en,
                    evento=evento,
                )
    except IntegrityError:
        # Dos reintentos simultáneos del mismo evento: gana el primero, el otro es duplicado.
        if evento is not None and evento.evidencia:
            evento.evidencia.delete(save=False)
        existente = Evento.objects.select_related("recipiente").get(
            id_externo=datos["id_externo"]
        )
        return _resultado(existente, creado=False)

    log.info("Evento %s registrado: %s en %s", evento.id_externo, veredicto, recipiente)
    return _resultado(evento, creado=True)

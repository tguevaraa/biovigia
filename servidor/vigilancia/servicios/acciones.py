"""Acciones correctivas (RF-10, PAN-08)."""
from __future__ import annotations

from django.db import transaction

from cuentas.models import AccionBitacora
from cuentas.servicios import registrar as registrar_bitacora

from ..models import AccionCorrectiva, Evento, Veredicto
from .errores import ErrorValidacion

LARGO_MAXIMO = 1000


def no_conformes_sin_accion():
    return (
        Evento.objects.select_related("recipiente__box")
        .filter(veredicto=Veredicto.NO_CONFORME, acciones__isnull=True)
        .order_by("-ocurrido_en")
    )


def listar():
    return (
        AccionCorrectiva.objects.select_related("registrada_por")
        .prefetch_related("eventos").order_by("-registrada_en")
    )


@transaction.atomic
def registrar_accion(descripcion: str, eventos_ids: list, usuario, responsable: str = "",
                     request=None) -> AccionCorrectiva:
    descripcion = (descripcion or "").strip()
    if not descripcion:
        raise ErrorValidacion("la descripción es obligatoria", campo="descripcion")
    if len(descripcion) > LARGO_MAXIMO:
        raise ErrorValidacion(f"máximo {LARGO_MAXIMO} caracteres", campo="descripcion")
    try:
        ids = sorted({int(i) for i in eventos_ids or []})
    except (TypeError, ValueError) as exc:
        raise ErrorValidacion("identificadores de evento no válidos", campo="eventos") from exc
    if not ids:
        raise ErrorValidacion("asocia la acción al menos a un evento", campo="eventos")
    eventos = list(Evento.objects.filter(pk__in=ids))
    if len(eventos) != len(ids):
        raise ErrorValidacion("alguno de los eventos no existe", campo="eventos")
    accion = AccionCorrectiva.objects.create(
        descripcion=descripcion, responsable=(responsable or "").strip()[:120],
        registrada_por=usuario)
    accion.eventos.set(eventos)
    registrar_bitacora(request, AccionBitacora.ACCION_CORRECTIVA,
                       f"Acción {accion.pk} sobre {len(eventos)} evento(s)", usuario)
    return accion

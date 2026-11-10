"""Estado de los recipientes y registro del recambio (RF-05, RF-08, HU-03)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from cuentas.models import AccionBitacora
from cuentas.servicios import registrar as registrar_bitacora

from ..models import Box, CambioEstado, EstadoRecipiente, Recambio, Recipiente, TipoRecipiente
from .errores import NoEncontrado, RecipienteNoContaminado
from .tiempo import inicio_del_dia, hoy


@dataclass
class CambioDelDia:
    hora: datetime
    recipiente: Recipiente
    de: str
    a: str
    evento_id: int | None
    recambio_id: int | None

    @property
    def descripcion(self) -> str:
        if self.a == EstadoRecipiente.CONTAMINADO:
            return "Pasó a contaminado"
        return "Recambio registrado; volvió a normal"


def recipientes_activos():
    return (
        Recipiente.objects.select_related("box", "evento_causa")
        .filter(box__activo=True)
        .order_by("box__codigo", "-tipo")
    )


def obtener_recipiente(box: str, tipo: str) -> Recipiente:
    try:
        return Recipiente.objects.select_related("box").get(box__codigo=box, tipo=tipo)
    except Recipiente.DoesNotExist as exc:
        raise NoEncontrado("El recipiente indicado no existe.", campo="tipo") from exc


def cambios_de_hoy() -> list[CambioDelDia]:
    desde = inicio_del_dia(hoy())
    cambios = (
        CambioEstado.objects.select_related("recipiente__box")
        .filter(ocurrido_en__gte=desde)
        .order_by("-ocurrido_en", "-id")
    )
    return [
        CambioDelDia(
            hora=timezone.localtime(c.ocurrido_en),
            recipiente=c.recipiente,
            de=c.estado_anterior,
            a=c.estado_nuevo,
            evento_id=c.evento_id,
            recambio_id=c.recambio_id,
        )
        for c in cambios
    ]


def ultimo_cambio(recipiente: Recipiente) -> CambioEstado | None:
    return recipiente.cambios.order_by("-ocurrido_en", "-id").first()


@transaction.atomic
def registrar_recambio(box: str, tipo: str, usuario, request=None) -> Recambio:
    """Restablece a normal un recipiente contaminado. El evento se conserva en el historial."""
    try:
        recipiente = (
            Recipiente.objects.select_for_update().select_related("box")
            .get(box__codigo=box, tipo=tipo)
        )
    except Recipiente.DoesNotExist as exc:
        raise NoEncontrado("El recipiente indicado no existe.", campo="tipo") from exc

    if recipiente.estado != EstadoRecipiente.CONTAMINADO:
        raise RecipienteNoContaminado()

    ahora = timezone.now()
    recambio = Recambio.objects.create(
        recipiente=recipiente,
        registrado_por=usuario,
        registrado_en=ahora,
        evento_causa=recipiente.evento_causa,
    )
    CambioEstado.objects.create(
        recipiente=recipiente,
        estado_anterior=EstadoRecipiente.CONTAMINADO,
        estado_nuevo=EstadoRecipiente.NORMAL,
        ocurrido_en=ahora,
        recambio=recambio,
    )
    recipiente.estado = EstadoRecipiente.NORMAL
    recipiente.contaminado_desde = None
    recipiente.evento_causa = None
    recipiente.save(update_fields=["estado", "contaminado_desde", "evento_causa"])
    registrar_bitacora(request, AccionBitacora.RECAMBIO, f"Recambio de {recipiente}", usuario)
    return recambio


@transaction.atomic
def crear_box(codigo: str, nombre: str = "") -> Box:
    """Crea un puesto con sus dos recipientes. Idempotente."""
    box, _ = Box.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
    for tipo in TipoRecipiente.values:
        Recipiente.objects.get_or_create(box=box, tipo=tipo)
    return box

"""Consulta de eventos (PAN-03, PAN-04) y acceso auditado a la evidencia."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import QuerySet

from cuentas.models import AccionBitacora
from cuentas.servicios import registrar as registrar_bitacora

from ..models import Evento, TipoRecipiente, Veredicto
from .errores import ErrorValidacion, NoEncontrado
from .tiempo import FUERA_DE_TURNO, rango_de_fechas, turnos

POR_PAGINA = 8  # contrato v1, sección 5


@dataclass
class Pagina:
    items: list[Evento]
    total: int
    pagina: int
    paginas: int

    @property
    def desde(self) -> int:
        return 0 if not self.total else (self.pagina - 1) * POR_PAGINA + 1

    @property
    def hasta(self) -> int:
        return min(self.pagina * POR_PAGINA, self.total)

    @property
    def rango_paginas(self) -> list[int | None]:
        """Números de página para el paginador, con ``None`` donde va «…»."""
        if self.paginas <= 7:
            return list(range(1, self.paginas + 1))
        visibles = {1, 2, self.paginas, self.pagina - 1, self.pagina, self.pagina + 1}
        resultado: list[int | None] = []
        previo = 0
        for n in sorted(p for p in visibles if 1 <= p <= self.paginas):
            if n - previo > 1:
                resultado.append(None)
            resultado.append(n)
            previo = n
        return resultado


def _fecha(valor: Any, campo: str) -> date | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except ValueError as exc:
        raise ErrorValidacion("formato de fecha AAAA-MM-DD", campo=campo) from exc


def filtrar(filtros: dict[str, Any]) -> QuerySet[Evento]:
    """Aplica los filtros de PAN-03. No existe filtro por persona (RNF-05)."""
    qs = Evento.objects.select_related("recipiente__box").prefetch_related("acciones")
    desde = _fecha(filtros.get("desde"), "desde")
    hasta = _fecha(filtros.get("hasta"), "hasta")
    if desde and hasta and desde > hasta:
        raise ErrorValidacion("«desde» no puede ser posterior a «hasta»", campo="desde")
    if desde:
        qs = qs.filter(ocurrido_en__gte=rango_de_fechas(desde, desde)[0])
    if hasta:
        qs = qs.filter(ocurrido_en__lt=rango_de_fechas(hasta, hasta)[1])

    turno = filtros.get("turno")
    if turno:
        validos = [t.codigo for t in turnos()] + [FUERA_DE_TURNO]
        if turno not in validos:
            raise ErrorValidacion(f"valores admitidos: {', '.join(validos)}", campo="turno")
        qs = qs.filter(turno=turno)

    recipiente = filtros.get("recipiente")
    if recipiente:
        if recipiente not in TipoRecipiente.values:
            raise ErrorValidacion("valores admitidos: rojo, comun", campo="recipiente")
        qs = qs.filter(recipiente__tipo=recipiente)

    veredicto = filtros.get("veredicto")
    if veredicto:
        if veredicto not in Veredicto.values:
            raise ErrorValidacion("valores admitidos: conforme, no_conforme", campo="veredicto")
        qs = qs.filter(veredicto=veredicto)

    box = filtros.get("box")
    if box:
        qs = qs.filter(recipiente__box__codigo=box)
    return qs.order_by("-ocurrido_en", "-id")


def paginar(qs: QuerySet[Evento], pagina: Any) -> Pagina:
    try:
        numero = max(1, int(pagina or 1))
    except (TypeError, ValueError) as exc:
        raise ErrorValidacion("debe ser un número entero", campo="pagina") from exc
    total = qs.count()
    paginas = max(1, math.ceil(total / POR_PAGINA))
    numero = min(numero, paginas)
    inicio = (numero - 1) * POR_PAGINA
    return Pagina(list(qs[inicio:inicio + POR_PAGINA]), total, numero, paginas)


def obtener(evento_id: int) -> Evento:
    try:
        return (
            Evento.objects.select_related("recipiente__box")
            .prefetch_related("acciones").get(pk=evento_id)
        )
    except Evento.DoesNotExist as exc:
        raise NoEncontrado("El evento no existe.") from exc


def estado_recipiente_tras(evento: Evento) -> str:
    """Estado en que quedó el recipiente justo después del evento."""
    cambio = evento.recipiente.cambios.filter(
        ocurrido_en__lte=evento.ocurrido_en
    ).order_by("-ocurrido_en", "-id").first()
    return cambio.estado_nuevo if cambio else "normal"


def abrir_evidencia(evento: Evento, usuario, request=None):
    """Devuelve el archivo de evidencia y deja constancia en la bitácora (RNF-14)."""
    if not evento.evidencia_disponible:
        raise NoEncontrado("La evidencia no está disponible.")
    registrar_bitacora(request, AccionBitacora.VER_EVIDENCIA, f"Evidencia de {evento.codigo}",
                       usuario)
    return evento.evidencia.open("rb")

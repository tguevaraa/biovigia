"""Cobertura de observación y periodos no observados (RNF-06).

El servicio de visión informa los tramos en los que la cámara estuvo entregando
fotogramas. Todo lo que queda fuera de esos tramos es «no observado». La regla del
contrato es que un tramo sin observar se devuelve como ``null`` y jamás como ``0``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import Box, TramoObservado


@dataclass(frozen=True)
class Intervalo:
    inicio: datetime
    fin: datetime

    @property
    def segundos(self) -> float:
        return max(0.0, (self.fin - self.inicio).total_seconds())


def _tolerancia() -> timedelta:
    return timedelta(seconds=settings.BIOVIGIA_TOLERANCIA_TRAMO_S)


@transaction.atomic
def registrar_tramo(box: Box, inicio: datetime, fin: datetime) -> TramoObservado:
    """Une el tramo informado con los existentes que se solapan o están contiguos."""
    if fin < inicio:
        inicio, fin = fin, inicio
    tol = _tolerancia()
    vecinos = list(
        TramoObservado.objects.select_for_update()
        .filter(box=box, fin__gte=inicio - tol, inicio__lte=fin + tol)
        .order_by("inicio")
    )
    if not vecinos:
        return TramoObservado.objects.create(box=box, inicio=inicio, fin=fin)
    base = vecinos[0]
    base.inicio = min([inicio] + [v.inicio for v in vecinos])
    base.fin = max([fin] + [v.fin for v in vecinos])
    base.save(update_fields=["inicio", "fin"])
    TramoObservado.objects.filter(pk__in=[v.pk for v in vecinos[1:]]).delete()
    return base


def tramos_en(desde: datetime, hasta: datetime, box: Box | None = None) -> list[Intervalo]:
    """Tramos observados que tocan [desde, hasta), recortados y fusionados entre boxes."""
    filtro = Q(fin__gt=desde, inicio__lt=hasta)
    if box is not None:
        filtro &= Q(box=box)
    crudos = [
        Intervalo(max(t.inicio, desde), min(t.fin, hasta))
        for t in TramoObservado.objects.filter(filtro).order_by("inicio")
    ]
    return fusionar(crudos)


def fusionar(intervalos: Iterable[Intervalo]) -> list[Intervalo]:
    ordenados = sorted(intervalos, key=lambda i: i.inicio)
    resultado: list[Intervalo] = []
    for actual in ordenados:
        if resultado and actual.inicio <= resultado[-1].fin:
            previo = resultado[-1]
            resultado[-1] = Intervalo(previo.inicio, max(previo.fin, actual.fin))
        else:
            resultado.append(actual)
    return resultado


def cobertura(tramos: Sequence[Intervalo], desde: datetime, hasta: datetime) -> float:
    """Segundos observados dentro de [desde, hasta). ``tramos`` debe venir fusionado."""
    total = 0.0
    for t in tramos:
        inicio, fin = max(t.inicio, desde), min(t.fin, hasta)
        if fin > inicio:
            total += (fin - inicio).total_seconds()
    return total


def huecos(tramos: Sequence[Intervalo], desde: datetime, hasta: datetime,
           minimo_s: float | None = None) -> list[Intervalo]:
    """Periodos no observados dentro de [desde, hasta), ignorando los muy cortos."""
    if minimo_s is None:
        minimo_s = settings.BIOVIGIA_HUECO_MINIMO_S
    resultado: list[Intervalo] = []
    cursor = desde
    for t in tramos:
        if t.fin <= desde or t.inicio >= hasta:
            continue
        if t.inicio > cursor:
            resultado.append(Intervalo(cursor, min(t.inicio, hasta)))
        cursor = max(cursor, t.fin)
        if cursor >= hasta:
            break
    if cursor < hasta:
        resultado.append(Intervalo(cursor, hasta))
    return [h for h in resultado if h.segundos >= minimo_s]


def latido_vigente(box: Box) -> bool:
    if box.ultimo_latido is None:
        return False
    edad = timezone.now() - box.ultimo_latido
    return edad.total_seconds() <= settings.BIOVIGIA_LATIDO_VENCIDO_S


def registrar_latido(box: Box, datos: dict) -> Box:
    """Actualiza el estado de salud del box e incorpora el tramo observado informado."""
    box.ultimo_latido = timezone.now()
    box.camara_conectada = bool(datos.get("camara_conectada", False))
    box.fps_medido = datos.get("fps")
    box.zonas_alineadas = datos.get("zonas_alineadas")
    box.modelo_en_uso = (datos.get("modelo") or "")[:40]
    box.cola_pendientes = int(datos.get("cola_pendientes") or 0)
    box.save(update_fields=[
        "ultimo_latido", "camara_conectada", "fps_medido", "zonas_alineadas",
        "modelo_en_uso", "cola_pendientes",
    ])
    for tramo in datos.get("tramos") or []:
        registrar_tramo(box, tramo["inicio"], tramo["fin"])
    return box

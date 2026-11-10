"""Resumen del turno para el tablero principal (PAN-02, contrato v1 sección 4)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from ..models import Box, EstadoRecipiente, Evento, Recipiente, Veredicto
from . import observacion
from .tiempo import Turno, ahora

ESTADO_OBSERVADO = "observado"
ESTADO_PARCIAL = "parcial"
ESTADO_SIN_OBSERVAR = "sin_observar"
ESTADO_PENDIENTE = "pendiente"


def _fmt(momento: datetime) -> str:
    return timezone.localtime(momento).strftime("%H:%M")


def _texto_huecos(huecos: list[observacion.Intervalo]) -> str:
    partes = [f"{_fmt(h.inicio)} a {_fmt(h.fin)}" for h in huecos]
    if not partes:
        return ""
    return "Sin observar de " + ", ".join(partes)


def cumplimiento(total: int, no_conformes: int) -> float | None:
    """Proporción de descartes conformes. ``None`` si no hubo descartes (no es 100 %)."""
    if not total:
        return None
    return round((total - no_conformes) / total, 3)


def resumen_turno(fecha: date, turno: Turno) -> dict[str, Any]:
    inicio, fin = turno.rango(fecha)
    momento = ahora()
    corte = min(fin, momento)  # lo que todavía no ocurrió no se cuenta como no observado

    eventos = Evento.objects.filter(ocurrido_en__gte=inicio, ocurrido_en__lt=fin)
    totales = eventos.aggregate(
        total=Count("id"),
        no_conformes=Count("id", filter=Q(veredicto=Veredicto.NO_CONFORME)),
    )
    conteo_hora: dict[int, dict[str, int]] = {}
    for ocurrido, veredicto in eventos.values_list("ocurrido_en", "veredicto"):
        h = timezone.localtime(ocurrido).hour
        celda = conteo_hora.setdefault(h, {"total": 0, "no_conformes": 0})
        celda["total"] += 1
        if veredicto == Veredicto.NO_CONFORME:
            celda["no_conformes"] += 1

    tramos = observacion.tramos_en(inicio, fin)
    huecos_turno = observacion.huecos(tramos, inicio, corte) if corte > inicio else []

    por_hora = []
    for hora in turno.horas:
        h_ini = inicio + timedelta(hours=hora - turno.hora_inicio)
        h_fin = h_ini + timedelta(hours=1)
        celda = conteo_hora.get(hora, {"total": 0, "no_conformes": 0})
        fila: dict[str, Any] = {"hora": f"{hora:02d}:00", "en_curso": h_ini <= momento < h_fin}
        if h_ini >= momento:
            fila.update(total=None, no_conformes=None, estado=ESTADO_PENDIENTE)
            por_hora.append(fila)
            continue
        h_corte = min(h_fin, momento)
        huecos_hora = observacion.huecos(tramos, h_ini, h_corte)
        sin_observar_s = sum(h.segundos for h in huecos_hora)
        observado_s = (h_corte - h_ini).total_seconds() - sin_observar_s
        if observado_s <= 0 and celda["total"] == 0:
            fila.update(total=None, no_conformes=None, estado=ESTADO_SIN_OBSERVAR,
                        detalle=_texto_huecos(huecos_hora) or "Sin observar")
        elif sin_observar_s > 0:
            fila.update(total=celda["total"], no_conformes=celda["no_conformes"],
                        estado=ESTADO_PARCIAL,
                        minutos_sin_observar=round(sin_observar_s / 60),
                        detalle=_texto_huecos(huecos_hora))
        else:
            fila.update(total=celda["total"], no_conformes=celda["no_conformes"],
                        estado=ESTADO_OBSERVADO)
        por_hora.append(fila)

    recipientes = []
    for r in Recipiente.objects.select_related("box").filter(box__activo=True):
        item = {"box": r.box.codigo, "tipo": r.tipo, "estado": r.estado}
        if r.estado == EstadoRecipiente.CONTAMINADO and r.contaminado_desde:
            item["contaminado_desde"] = timezone.localtime(r.contaminado_desde).isoformat(
                timespec="seconds")
        recipientes.append(item)

    vision = []
    for box in Box.objects.filter(activo=True):
        vision.append({
            "box": box.codigo,
            "conectado": observacion.latido_vigente(box),
            "camara_conectada": box.camara_conectada,
            "fps": box.fps_medido,
            "ultimo_latido": (timezone.localtime(box.ultimo_latido).isoformat(timespec="seconds")
                              if box.ultimo_latido else None),
        })

    total = totales["total"]
    no_conformes = totales["no_conformes"]
    return {
        "fecha": fecha.isoformat(),
        "turno": turno.codigo,
        "actualizado_en": momento.isoformat(timespec="seconds"),
        "kpis": {
            "descartes": total,
            "no_conformes": no_conformes,
            "cumplimiento": cumplimiento(total, no_conformes),
            "proporcion_no_conformes": round(no_conformes / total, 3) if total else None,
            "recipientes_contaminados": sum(
                1 for r in recipientes if r["estado"] == EstadoRecipiente.CONTAMINADO),
            "periodos_no_observados": len(huecos_turno),
            "minutos_sin_observar": round(sum(h.segundos for h in huecos_turno) / 60),
        },
        "por_hora": por_hora,
        "recipientes": recipientes,
        "vision": vision,
    }

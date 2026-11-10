"""Indicadores del periodo y exportación de reportes (PAN-07, RF-09, HU-04).

La exportación usa el patrón Strategy (Tabla 39): el formato se elige sin tocar el
servicio que arma los datos. Ningún reporte contiene personas (RNF-05).
"""
from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from ..models import CambioEstado, EstadoRecipiente, Veredicto
from . import observacion
from .errores import ErrorValidacion
from .eventos import filtrar
from .tablero import cumplimiento
from .tiempo import etiqueta_turno, rango_de_fechas, turno_por_codigo, turnos

DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MAX_DIAS_PERIODO = 366


@dataclass
class Periodo:
    desde: date
    hasta: date
    turno: str = ""
    recipiente: str = ""

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1

    def anterior(self) -> "Periodo":
        return Periodo(self.desde - timedelta(days=self.dias),
                       self.desde - timedelta(days=1), self.turno, self.recipiente)

    @property
    def filtros(self) -> dict[str, Any]:
        return {"desde": self.desde, "hasta": self.hasta,
                "turno": self.turno, "recipiente": self.recipiente}

    @property
    def descripcion(self) -> str:
        texto = f"Del {self.desde:%d/%m/%Y} al {self.hasta:%d/%m/%Y}"
        if self.turno:
            texto += f" · turno {etiqueta_turno(self.turno).lower()}"
        if self.recipiente:
            texto += f" · recipiente {'rojo' if self.recipiente == 'rojo' else 'común'}"
        return texto


def periodo_desde(params: dict[str, Any]) -> Periodo:
    """Construye el periodo desde parámetros de consulta. Por defecto, los últimos 7 días."""
    hoy = timezone.localdate()
    try:
        hasta = date.fromisoformat(params["hasta"]) if params.get("hasta") else hoy
        desde = (date.fromisoformat(params["desde"]) if params.get("desde")
                 else hasta - timedelta(days=6))
    except ValueError as exc:
        raise ErrorValidacion("formato de fecha AAAA-MM-DD", campo="desde") from exc
    if desde > hasta:
        raise ErrorValidacion("«desde» no puede ser posterior a «hasta»", campo="desde")
    if (hasta - desde).days + 1 > MAX_DIAS_PERIODO:
        raise ErrorValidacion("el periodo no puede superar un año", campo="desde")
    turno = params.get("turno") or ""
    if turno and turno_por_codigo(turno) is None:
        raise ErrorValidacion("turno no válido", campo="turno")
    recipiente = params.get("recipiente") or ""
    if recipiente not in ("", "rojo", "comun"):
        raise ErrorValidacion("valores admitidos: rojo, comun", campo="recipiente")
    return Periodo(desde, hasta, turno, recipiente)


def _horas_turno(turno: str) -> list[int]:
    lista = [turno_por_codigo(turno)] if turno else turnos()
    return [h for t in lista if t for h in t.horas]


def _totales(periodo: Periodo) -> dict[str, int]:
    return filtrar(periodo.filtros).aggregate(
        total=Count("id"), no_conformes=Count("id", filter=Q(veredicto=Veredicto.NO_CONFORME)))


@dataclass
class Indicadores:
    periodo: Periodo
    kpis: dict[str, Any]
    anterior: dict[str, Any]
    evolucion_diaria: list[dict[str, Any]]
    mapa_calor: dict[str, Any]
    sin_accion: int
    huecos: list[observacion.Intervalo] = field(default_factory=list)

    @property
    def hay_eventos(self) -> bool:
        return bool(self.kpis["descartes"])

    def como_dict(self) -> dict[str, Any]:
        return {
            "periodo": {"desde": self.periodo.desde.isoformat(),
                        "hasta": self.periodo.hasta.isoformat(),
                        "turno": self.periodo.turno or None,
                        "recipiente": self.periodo.recipiente or None},
            "kpis": self.kpis,
            "anterior": self.anterior,
            "evolucion_diaria": self.evolucion_diaria,
            "mapa_calor": self.mapa_calor,
            "eventos_no_conformes_sin_accion": self.sin_accion,
        }


def calcular(periodo: Periodo) -> Indicadores:
    inicio, fin = rango_de_fechas(periodo.desde, periodo.hasta)
    eventos = filtrar(periodo.filtros)
    totales = _totales(periodo)
    previo = _totales(periodo.anterior())
    contaminaciones = CambioEstado.objects.filter(
        ocurrido_en__gte=inicio, ocurrido_en__lt=fin, estado_nuevo=EstadoRecipiente.CONTAMINADO)

    horas = _horas_turno(periodo.turno)
    tramos = observacion.tramos_en(inicio, fin)
    momento = timezone.localtime()

    # Conteos por día y por (día de la semana, hora).
    por_dia: dict[date, dict[str, int]] = {}
    calor: dict[tuple[int, int], int] = {}
    for ocurrido, veredicto in eventos.values_list("ocurrido_en", "veredicto"):
        local = timezone.localtime(ocurrido)
        celda = por_dia.setdefault(local.date(), {"total": 0, "no_conformes": 0})
        celda["total"] += 1
        if veredicto == Veredicto.NO_CONFORME:
            celda["no_conformes"] += 1
            clave = (local.weekday(), local.hour)
            calor[clave] = calor.get(clave, 0) + 1

    # Cobertura de cada hora de turno: periodos no observados y celdas sin observar.
    huecos_periodo: list[observacion.Intervalo] = []
    cubierto: dict[tuple[int, int], float] = {}
    dias_con_hora: set[int] = set()
    for i in range(periodo.dias):
        dia = periodo.desde + timedelta(days=i)
        d_ini = rango_de_fechas(dia, dia)[0]
        for h in horas:
            h_ini = d_ini + timedelta(hours=h)
            h_fin = min(h_ini + timedelta(hours=1), momento)
            if h_fin <= h_ini:
                continue
            dias_con_hora.add(dia.weekday())
            clave = (dia.weekday(), h)
            cubierto[clave] = cubierto.get(clave, 0.0) + observacion.cobertura(tramos, h_ini, h_fin)
            huecos_periodo.extend(observacion.huecos(tramos, h_ini, h_fin))
    huecos_periodo = observacion.fusionar(huecos_periodo)

    evolucion = []
    for i in range(periodo.dias):
        dia = periodo.desde + timedelta(days=i)
        celda = por_dia.get(dia)
        d_ini = rango_de_fechas(dia, dia)[0]
        observado = celda is not None or any(
            observacion.cobertura(tramos, d_ini + timedelta(hours=h),
                                  d_ini + timedelta(hours=h + 1)) > 0 for h in horas)
        futuro = d_ini > momento
        evolucion.append({
            "fecha": dia.isoformat(),
            "etiqueta": f"{DIAS[dia.weekday()]} {dia.day}",
            # Un día que la cámara nunca observó va en null, no en cero (RNF-06).
            "total": (celda or {}).get("total", 0) if observado else None,
            "no_conformes": (celda or {}).get("no_conformes", 0) if observado else None,
            "estado": "pendiente" if futuro else ("observado" if observado else "sin_observar"),
        })

    filas = []
    for wd in sorted(dias_con_hora):
        valores = []
        for h in horas:
            clave = (wd, h)
            if clave not in cubierto:
                valores.append(None)        # hora futura: aún no ocurre
            elif cubierto[clave] <= 0 and not calor.get(clave):
                valores.append(None)        # nunca observada: null, no cero (RNF-06)
            else:
                valores.append(calor.get(clave, 0))
        filas.append({"dia": DIAS[wd], "valores": valores})
    maximo = max((v for f in filas for v in f["valores"] if v), default=0)

    total, nc = totales["total"], totales["no_conformes"]
    sin_accion = eventos.filter(veredicto=Veredicto.NO_CONFORME, acciones__isnull=True).count()
    return Indicadores(
        periodo=periodo,
        kpis={
            "descartes": total,
            "no_conformes": nc,
            "cumplimiento": cumplimiento(total, nc),
            "proporcion_no_conformes": round(nc / total, 3) if total else None,
            "recipientes_contaminados": contaminaciones.count(),
            "minutos_sin_observar": round(sum(h.segundos for h in huecos_periodo) / 60),
            "desconexiones": len(huecos_periodo),
        },
        anterior={
            "descartes": previo["total"],
            "cumplimiento": cumplimiento(previo["total"], previo["no_conformes"]),
        },
        evolucion_diaria=evolucion,
        mapa_calor={"horas": [f"{h:02d}" for h in horas], "filas": filas, "maximo": maximo},
        sin_accion=sin_accion,
        huecos=huecos_periodo,
    )


# --- Exportadores (Strategy) ---------------------------------------------------------------

class Exportador(ABC):
    formato: str
    tipo_mime: str
    extension: str

    @abstractmethod
    def generar(self, indicadores: Indicadores) -> bytes: ...

    def nombre_archivo(self, periodo: Periodo) -> str:
        return f"biovigia_{periodo.desde:%Y%m%d}_{periodo.hasta:%Y%m%d}.{self.extension}"


class ExportadorCSV(Exportador):
    formato = "csv"
    tipo_mime = "text/csv; charset=utf-8"
    extension = "csv"
    COLUMNAS = ["fecha", "hora", "turno", "box", "recipiente", "veredicto", "confianza",
                "accion_correctiva"]

    def generar(self, indicadores: Indicadores) -> bytes:
        salida = io.StringIO()
        escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
        escritor.writerow(self.COLUMNAS)
        eventos = filtrar(indicadores.periodo.filtros).order_by("ocurrido_en", "id")
        for e in eventos:
            local = timezone.localtime(e.ocurrido_en)
            acciones = " | ".join(a.descripcion.replace("\n", " ") for a in e.acciones.all())
            escritor.writerow([
                local.strftime("%Y-%m-%d"), local.strftime("%H:%M:%S"),
                etiqueta_turno(e.turno), e.recipiente.box.codigo,
                e.recipiente.get_tipo_display(), e.get_veredicto_display(),
                f"{e.confianza:.3f}".replace(".", ","), acciones,
            ])
        # BOM para que Excel en español abra los acentos correctamente.
        return ("﻿" + salida.getvalue()).encode("utf-8")


class ExportadorPDF(Exportador):
    formato = "pdf"
    tipo_mime = "application/pdf"
    extension = "pdf"

    def generar(self, indicadores: Indicadores) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                                topMargin=2 * cm, bottomMargin=2 * cm,
                                title="Reporte BioVigIA", author="BioVigIA")
        estilos = getSampleStyleSheet()
        azul = colors.HexColor("#1C3247")
        k = indicadores.kpis
        cumpl = "—" if k["cumplimiento"] is None else f"{k['cumplimiento'] * 100:.1f} %"
        sin_obs = f"{k['minutos_sin_observar'] // 60} h {k['minutos_sin_observar'] % 60:02d} min"

        def tabla(filas, anchos):
            t = Table(filas, colWidths=anchos)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), azul),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CED6")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F5F8")]),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ]))
            return t

        contenido = [
            Paragraph("BioVigIA · Reporte de indicadores", estilos["Title"]),
            Paragraph(indicadores.periodo.descripcion, estilos["Normal"]),
            Paragraph(f"Generado el {timezone.localtime():%d/%m/%Y %H:%M}", estilos["Normal"]),
            Spacer(1, 0.5 * cm),
            Paragraph("Indicadores del periodo", estilos["Heading2"]),
            tabla([
                ["Indicador", "Valor"],
                ["Descartes registrados", str(k["descartes"])],
                ["Descartes no conformes", str(k["no_conformes"])],
                ["Cumplimiento", cumpl],
                ["Veces que un recipiente quedó contaminado", str(k["recipientes_contaminados"])],
                ["Tiempo sin observar", sin_obs],
                ["Periodos no observados", str(k["desconexiones"])],
                ["No conformes sin acción correctiva", str(indicadores.sin_accion)],
            ], [11 * cm, 5 * cm]),
            Spacer(1, 0.5 * cm),
            Paragraph("Evolución diaria", estilos["Heading2"]),
            tabla([["Día", "Descartes", "No conformes"]] + [
                [d["fecha"],
                 "sin observar" if d["total"] is None else str(d["total"]),
                 "—" if d["no_conformes"] is None else str(d["no_conformes"])]
                for d in indicadores.evolucion_diaria
            ], [6 * cm, 5 * cm, 5 * cm]),
        ]
        if indicadores.huecos:
            contenido += [Spacer(1, 0.5 * cm),
                          Paragraph("Periodos no observados", estilos["Heading2"]),
                          Paragraph("En estos tramos la cámara no observó; no equivalen a cero "
                                    "eventos.", estilos["Normal"]),
                          tabla([["Desde", "Hasta", "Minutos"]] + [
                              [f"{timezone.localtime(h.inicio):%d/%m %H:%M}",
                               f"{timezone.localtime(h.fin):%d/%m %H:%M}",
                               str(round(h.segundos / 60))]
                              for h in indicadores.huecos[:60]
                          ], [6 * cm, 6 * cm, 4 * cm])]
        contenido += [Spacer(1, 0.8 * cm), Paragraph(
            "Los indicadores se presentan agregados por turno y por recipiente. Este reporte no "
            "identifica a pacientes ni a trabajadores (RNF-05).", estilos["Italic"])]
        doc.build(contenido)
        return buffer.getvalue()


EXPORTADORES: dict[str, Exportador] = {e.formato: e for e in (ExportadorCSV(), ExportadorPDF())}


def exportador_para(formato: str) -> Exportador:
    try:
        return EXPORTADORES[formato]
    except KeyError as exc:
        raise ErrorValidacion("formatos admitidos: csv, pdf", campo="formato") from exc

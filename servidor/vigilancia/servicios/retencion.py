"""Retención limitada de la evidencia (RNF-17, HU-05 criterio 2).

El evento y su veredicto se conservan siempre; solo se borra la imagen recortada.
Se ejecuta con ``python manage.py depurar_evidencia`` (programable en el Programador de
tareas de Windows o en cron) y, además, de forma oportunista como máximo una vez por hora
cuando alguien abre el tablero, para que el borrado ocurra aunque nadie programe la tarea.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from ..models import Evento, Parametros

log = logging.getLogger("biovigia.retencion")
CLAVE_CACHE = "biovigia:ultima_depuracion"


def depurar_evidencia_vencida() -> int:
    dias = Parametros.actual().retencion_dias
    limite = timezone.now() - timedelta(days=dias)
    vencidos = Evento.objects.filter(
        ocurrido_en__lt=limite, evidencia_eliminada_en__isnull=True).exclude(evidencia="")
    borrados = 0
    for evento in vencidos.iterator():
        try:
            evento.evidencia.delete(save=False)
        except OSError:  # el archivo ya no estaba; igual se marca como eliminado
            log.warning("No se encontró el archivo de evidencia de %s", evento.codigo)
        evento.evidencia = ""
        evento.evidencia_eliminada_en = timezone.now()
        evento.save(update_fields=["evidencia", "evidencia_eliminada_en"])
        borrados += 1
    if borrados:
        log.info("Retención: %s evidencia(s) eliminada(s) (más de %s días)", borrados, dias)
    return borrados


def depurar_si_corresponde() -> None:
    if cache.add(CLAVE_CACHE, True, timeout=3600):
        depurar_evidencia_vencida()

"""Disparador por mano: solo cuenta como descarte la gasa que llega con una mano.

Primera etapa de la detección en dos etapas (``docs/deteccion-dos-etapas.md``). La gasa
es pequeña y un reflejo o un papel blanco se le parecen; la mano es grande y se detecta
bien. Este módulo responde una sola pregunta por fotograma: **¿hay una mano en el área de
aproximación de los recipientes?** El motor de reglas usa la respuesta para decidir qué
trayectorias pueden confirmarse.

No guarda estado ni tiempos: el tiempo de gracia lo lleva ``MotorConfirmacion``, que es
quien conoce las trayectorias.
"""
from __future__ import annotations

from dataclasses import dataclass

from .configuracion import ParametrosReglas
from .tipos import MANO, Deteccion
from .zonas import ConjuntoZonas


@dataclass(frozen=True)
class EstadoMano:
    activa: bool
    confianza: float = 0.0


SIN_MANO = EstadoMano(False, 0.0)


class DisparadorMano:
    def __init__(self, parametros: ParametrosReglas, ancho: int = 640, alto: int = 480) -> None:
        self.p = parametros
        self.ancho, self.alto = ancho, alto

    def evaluar(self, detecciones: list[Deteccion], zonas: ConjuntoZonas) -> EstadoMano:
        """Mano más confiable cuya caja toca el área de aproximación de algún recipiente."""
        manos = [d for d in detecciones
                 if d.clase == MANO and d.confianza >= self.p.umbral_confianza]
        if not manos:
            return SIN_MANO
        areas = [z.caja_px(self.ancho, self.alto, margen=self.p.margen_mano) for z in zonas]
        if not areas:
            # Sin zonas no hay área que comprobar: cualquier mano en el cuadro cuenta.
            return EstadoMano(True, max(m.confianza for m in manos))
        cerca = [m for m in manos if any(_se_tocan(m, a) for a in areas)]
        if not cerca:
            return SIN_MANO
        return EstadoMano(True, max(m.confianza for m in cerca))


def _se_tocan(d: Deteccion, caja: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = caja
    return d.x0 <= x1 and d.x1 >= x0 and d.y0 <= y1 and d.y1 >= y0

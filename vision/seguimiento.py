"""Seguimiento de la gasa entre fotogramas: asigna un identificador estable a cada objeto.

Asociación voraz por distancia del centro, con compuerta. Es deliberadamente simple: en
la estación de descarte hay una o dos gasas a la vez, y un seguidor propio no depende del
detector (sirve igual para YOLO, ONNX o el detector de desarrollo) y se prueba sin cámara.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from .tipos import Deteccion


@dataclass
class Pista:
    id: int
    deteccion: Deteccion
    creada_t: float
    ultima_t: float
    vistas: int = 1

    @property
    def centro(self) -> tuple[float, float]:
        return self.deteccion.centro


@dataclass
class Seguidor:
    max_distancia_px: float = 90.0
    max_perdida_s: float = 1.5
    pistas: dict[int, Pista] = field(default_factory=dict)
    _contador: itertools.count = field(default_factory=lambda: itertools.count(1))

    def actualizar(self, detecciones: list[Deteccion], t: float) -> list[tuple[Pista, bool]]:
        """Asocia las detecciones del fotograma. Devuelve (pista, es_nueva) por detección."""
        self._podar(t)
        activas = list(self.pistas.values())
        pares = []
        for i, pista in enumerate(activas):
            px, py = pista.centro
            for j, det in enumerate(detecciones):
                dx, dy = det.centro
                distancia = math.hypot(px - dx, py - dy)
                # La compuerta crece con el tiempo perdido: la gasa en caída se mueve rápido.
                hueco = max(0.0, t - pista.ultima_t)
                if distancia <= self.max_distancia_px * (1 + 2 * hueco):
                    pares.append((distancia, i, j))
        pares.sort()
        usadas_p, usadas_d = set(), set()
        resultado: list[tuple[Pista, bool]] = []
        for _, i, j in pares:
            if i in usadas_p or j in usadas_d:
                continue
            usadas_p.add(i)
            usadas_d.add(j)
            pista = activas[i]
            pista.deteccion = detecciones[j]
            pista.ultima_t = t
            pista.vistas += 1
            resultado.append((pista, False))
        for j, det in enumerate(detecciones):
            if j not in usadas_d:
                nueva = Pista(next(self._contador), det, t, t)
                self.pistas[nueva.id] = nueva
                resultado.append((nueva, True))
        return resultado

    def _podar(self, t: float) -> None:
        for pid in [p.id for p in self.pistas.values() if t - p.ultima_t > self.max_perdida_s]:
            del self.pistas[pid]

    def olvidar(self, pista_id: int) -> None:
        self.pistas.pop(pista_id, None)

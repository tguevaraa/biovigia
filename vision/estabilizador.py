"""Estabiliza en el tiempo las cajas de objetos casi quietos (los recipientes).

El detector decide fotograma por fotograma: si la confianza en un tacho ronda el umbral,
la caja aparece y desaparece (parpadea), y si una mano lo tapa un instante, se pierde.
Para las zonas dinámicas eso no sirve: la zona de un tacho no puede desaparecer justo
cuando cae la gasa. Este módulo aplica tres ideas simples:

* **Histéresis.** Un objeto nuevo necesita confianza alta (``umbral_alta``) para aparecer,
  pero uno ya conocido se mantiene con confianza baja (``umbral_baja``).
* **Retención.** Si un objeto conocido no se detecta, se conserva su última caja durante
  ``retener_s`` segundos antes de darlo por perdido.
* **Suavizado.** La caja se mueve hacia la nueva detección con un promedio exponencial
  (``alfa``), así no tiembla de un fotograma a otro.

Además, un objeto solo se publica tras ``min_vistas`` detecciones, para que un falso
positivo de un fotograma no llegue a dibujarse.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from .tipos import Deteccion


def iou(a: Deteccion, b: Deteccion) -> float:
    """Intersección sobre unión de dos cajas (0 = no se tocan, 1 = iguales)."""
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = (a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter
    return inter / union if union > 0 else 0.0


def contenida(a: Deteccion, b: Deteccion) -> float:
    """Fracción del área de ``a`` que cae dentro de ``b`` (1 = ``a`` está entera en ``b``)."""
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    area = (a.x1 - a.x0) * (a.y1 - a.y0)
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0) / area if area > 0 else 0.0


def quitar_contenidas(detecciones: list[Deteccion], umbral: float = 0.85) -> list[Deteccion]:
    """Descarta las cajas que caen casi enteras dentro de otra de la misma clase con más
    confianza. El detector a veces da cuerpo entero y medio cuerpo de la misma persona;
    su supresión propia (por IoU) no las une porque la unión es grande."""
    quedan: list[Deteccion] = []
    for d in sorted(detecciones, key=lambda d: d.confianza, reverse=True):
        if all(d.clase != q.clase or contenida(d, q) < umbral for q in quedan):
            quedan.append(d)
    return quedan


@dataclass
class ObjetoEstable:
    id: int
    caja: Deteccion
    visto_t: float
    vistas: int = 1

    def retenido(self, t: float) -> bool:
        """True si en este instante se muestra por retención, sin detección nueva."""
        return t > self.visto_t


class Estabilizador:
    def __init__(self, umbral_alta: float = 0.35, umbral_baja: float = 0.15,
                 retener_s: float = 1.5, alfa: float = 0.4, iou_minimo: float = 0.3,
                 min_vistas: int = 2) -> None:
        self.umbral_alta, self.umbral_baja = umbral_alta, umbral_baja
        self.retener_s, self.alfa = retener_s, alfa
        self.iou_minimo, self.min_vistas = iou_minimo, min_vistas
        self._objetos: list[ObjetoEstable] = []
        self._ids = itertools.count(1)

    @property
    def ids_vivos(self) -> set[int]:
        """Objetos que se siguen recordando, publicados o no (para limpiar estado externo)."""
        return {o.id for o in self._objetos}

    def actualizar(self, detecciones: list[Deteccion], t: float) -> list[ObjetoEstable]:
        """Incorpora las detecciones del fotograma (con su confianza, sin filtrar por
        ``umbral_alta``: el filtro lo hace este método) y devuelve los objetos estables."""
        candidatas = quitar_contenidas([d for d in detecciones
                                        if d.confianza >= self.umbral_baja])
        libres = list(self._objetos)
        for d in candidatas:
            pares = [(iou(o.caja, d), o) for o in libres if o.caja.clase == d.clase]
            mejor_iou, mejor = max(pares, key=lambda p: p[0], default=(0.0, None))
            if mejor is not None and mejor_iou >= self.iou_minimo:
                mejor.caja = self._suavizar(mejor.caja, d)
                mejor.visto_t = t
                mejor.vistas += 1
                libres.remove(mejor)
            elif d.confianza >= self.umbral_alta:
                self._objetos.append(ObjetoEstable(next(self._ids), d, t))
        self._objetos = [o for o in self._objetos if t - o.visto_t <= self.retener_s]
        return [o for o in self._objetos if o.vistas >= self.min_vistas]

    def _suavizar(self, previa: Deteccion, nueva: Deteccion) -> Deteccion:
        a = self.alfa

        def mezcla(p: float, n: float) -> float:
            return (1 - a) * p + a * n

        return Deteccion(nueva.clase, max(nueva.confianza, mezcla(previa.confianza, nueva.confianza)),
                         mezcla(previa.x0, nueva.x0), mezcla(previa.y0, nueva.y0),
                         mezcla(previa.x1, nueva.x1), mezcla(previa.y1, nueva.y1))

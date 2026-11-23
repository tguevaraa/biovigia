"""Zonas de los recipientes a partir de los tachos que el modelo ve, fotograma a fotograma.

No hay polígonos dibujados a mano: si alguien mueve un tacho, o la cámara, la zona se mueve
con él. En cada fotograma:

1. Los tachos detectados se estabilizan en el tiempo (vision/estabilizador.py): la caja no
   tiembla y, si alguien tapa el tacho (la persona que se acerca a tirar la gasa queda
   justo delante), se mantiene ``retener_s`` segundos. Un tacho casi nunca se mueve, así
   que se retiene bastante; si lo mueven, gana la posición vista más recientemente.
2. Cada tacho estable guarda una votación de su tipo (rojo o común, según el color), para
   que un fotograma con otra luz no lo cambie de tipo.
3. La zona de cada tipo es la caja de su tacho, ampliada a los costados y sobre todo hacia
   arriba: la gasa se suelta por encima de la boca y su última observación suele quedar
   ahí, no dentro de la caja.

Si hay dos tachos del mismo tipo, se usa el visto más recientemente (y, a igualdad, el de
mayor confianza): el motor de reglas trabaja con una zona por tipo (ConjuntoZonas).
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from .estabilizador import Estabilizador, iou
from .tipos import COMUN, RECIPIENTE, RECIPIENTE_COMUN, RECIPIENTE_ROJO, ROJO, Deteccion
from .zonas import ConjuntoZonas, Zona

TIPO_DE_CLASE = {RECIPIENTE_ROJO: ROJO, RECIPIENTE_COMUN: COMUN}


class ZonasDinamicas:
    def __init__(self, ancho: int = 640, alto: int = 480, margen_lado: float = 0.15,
                 margen_arriba: float = 0.5, umbral_alta: float = 0.3, umbral_baja: float = 0.12,
                 retener_s: float = 20.0) -> None:
        self.ancho, self.alto = ancho, alto
        self.margen_lado, self.margen_arriba = margen_lado, margen_arriba
        # El tipo no entra en el estabilizador: un tacho es un tacho aunque un fotograma lo
        # vea de otro color. El tipo se decide por votación (abajo).
        self.estabilizador = Estabilizador(umbral_alta=umbral_alta, umbral_baja=umbral_baja,
                                           retener_s=retener_s)
        self._votos: dict[int, Counter] = {}
        self.visibles: dict[str, bool] = {ROJO: False, COMUN: False}

    def actualizar(self, detecciones: list[Deteccion], t: float) -> ConjuntoZonas:
        tachos = [d for d in detecciones if d.clase in TIPO_DE_CLASE]
        neutros = [Deteccion(RECIPIENTE, d.confianza, d.x0, d.y0, d.x1, d.y1) for d in tachos]
        objetos = self.estabilizador.actualizar(neutros, t)

        vivos = self.estabilizador.ids_vivos
        self._votos = {k: v for k, v in self._votos.items() if k in vivos}
        for o in objetos:
            mejor = max(tachos, key=lambda d: iou(d, o.caja), default=None)
            if mejor is not None and iou(mejor, o.caja) >= 0.3:
                self._votos.setdefault(o.id, Counter())[TIPO_DE_CLASE[mejor.clase]] += 1

        elegidos: dict[str, tuple[tuple[float, float], Deteccion]] = {}
        for o in objetos:
            votos = self._votos.get(o.id)
            if not votos:
                continue
            tipo = votos.most_common(1)[0][0]
            orden = (o.visto_t, o.caja.confianza)
            if tipo not in elegidos or orden > elegidos[tipo][0]:
                elegidos[tipo] = (orden, o.caja)
        self.visibles = {ROJO: ROJO in elegidos, COMUN: COMUN in elegidos}
        return ConjuntoZonas(self._zona(tipo, caja) for tipo, (_, caja) in elegidos.items())

    def _zona(self, tipo: str, d: Deteccion) -> Zona:
        w, h = d.x1 - d.x0, d.y1 - d.y0
        x0 = max(0.0, d.x0 - w * self.margen_lado) / self.ancho
        x1 = min(float(self.ancho), d.x1 + w * self.margen_lado) / self.ancho
        y0 = max(0.0, d.y0 - h * self.margen_arriba) / self.alto
        y1 = min(float(self.alto), d.y1) / self.alto
        return Zona(tipo, ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))

    @property
    def alguno_visible(self) -> Optional[bool]:
        return any(self.visibles.values())

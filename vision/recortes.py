"""Etapa 2 de la detección: buscar objetos pequeños en recortes de alta resolución.

El detector trabaja con la imagen reducida (640 px de ancho). Una gasa que en la cámara
del teléfono (1920 × 1080) ocupa 30 px queda en unos 10 px: no se ve. Si en cambio se
recorta del ORIGINAL la zona donde puede estar (alrededor de una persona o de la boca de un
tacho) y se pasa ese recorte al detector, la gasa queda varias veces más grande.

Este módulo no sabe de modelos ni de cámaras: recibe la imagen original, las regiones de
interés (en píxeles del original) y una función ``detectar(recorte) -> [Deteccion]``, y
devuelve las detecciones ya llevadas a coordenadas del original. Así se prueba sin GPU.
Ver docs/deteccion-dos-etapas.md.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .estabilizador import iou
from .tipos import Deteccion

Detectar = Callable[[np.ndarray], list[Deteccion]]


def region_de_busqueda(d: Deteccion, ancho: int, alto: int, margen: float = 0.25,
                       lado_min: int = 320) -> tuple[int, int, int, int]:
    """Caja ampliada ``margen`` hacia cada lado, de al menos ``lado_min`` px y dentro de la
    imagen. Un lado mínimo evita recortes diminutos que el detector ampliaría de más."""
    w, h = d.x1 - d.x0, d.y1 - d.y0
    cx, cy = (d.x0 + d.x1) / 2, (d.y0 + d.y1) / 2
    w2 = max(w * (1 + 2 * margen), lado_min) / 2
    h2 = max(h * (1 + 2 * margen), lado_min) / 2
    x0, x1 = max(0, int(cx - w2)), min(ancho, int(cx + w2))
    y0, y1 = max(0, int(cy - h2)), min(alto, int(cy + h2))
    return x0, y0, x1, y1


def fusionar_regiones(regiones: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Une las regiones que se solapan, para no analizar dos veces la misma zona."""
    pendientes = sorted(regiones)
    unidas: list[list[int]] = []
    for x0, y0, x1, y1 in pendientes:
        for u in unidas:
            if x0 < u[2] and u[0] < x1 and y0 < u[3] and u[1] < y1:
                u[0], u[1] = min(u[0], x0), min(u[1], y0)
                u[2], u[3] = max(u[2], x1), max(u[3], y1)
                break
        else:
            unidas.append([x0, y0, x1, y1])
    return [tuple(u) for u in unidas]


# Cuánto se amplía la búsqueda alrededor de cada tipo de guía, en veces su ancho y alto.
# Una persona ya abarca sus manos. Un tacho, en cambio, es chico y la gasa llega desde
# afuera en una mano: se busca en su zona de aproximación (como el disparador de la etapa 1).
# Valores PROVISIONALES. Medición del 21/11/2026 con los clips propios alejados 3 veces:
# un recorte que devuelve la escena a su tamaño original recupera la gasa (0,4 % → 9,2 %,
# igual que de cerca), pero con biovigia-gasas-v0.1 ningún margen alrededor del tacho
# funcionó (0 %), porque ese modelo solo reconoce gasas en una escala muy concreta.
# Ajustar con un modelo entrenado con gasas reales a varias escalas.
MARGENES = {"persona": 0.25, "recipiente": 1.5}


def buscar_en_recortes(original: np.ndarray, guias: list[Deteccion], detectar: Detectar,
                       margen: float | None = None, lado_min: int = 320,
                       iou_duplicado: float = 0.5) -> list[Deteccion]:
    """Analiza un recorte del original alrededor de cada guía (personas, tachos) y devuelve
    lo encontrado en coordenadas del original, sin duplicados entre recortes. Sin ``margen``,
    se usa el de ``MARGENES`` según la clase de cada guía."""
    alto, ancho = original.shape[:2]
    regiones = fusionar_regiones([
        region_de_busqueda(g, ancho, alto,
                           margen if margen is not None else MARGENES.get(g.clase, 0.25),
                           lado_min)
        for g in guias])
    halladas: list[Deteccion] = []
    for x0, y0, x1, y1 in regiones:
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        for d in detectar(original[y0:y1, x0:x1]):
            halladas.append(Deteccion(d.clase, d.confianza, d.x0 + x0, d.y0 + y0,
                                      d.x1 + x0, d.y1 + y0))
    quedan: list[Deteccion] = []
    for d in sorted(halladas, key=lambda d: d.confianza, reverse=True):
        if all(d.clase != q.clase or iou(d, q) < iou_duplicado for q in quedan):
            quedan.append(d)
    return quedan

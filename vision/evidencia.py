"""Recorte de evidencia limitado a la zona del recipiente (RF-06, RNF-03).

Nunca se guarda ni se envía el fotograma completo: solo el rectángulo que envuelve el
polígono de la boca del recipiente, con un margen pequeño.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .zonas import Zona

CALIDAD_JPEG = 85
MAX_BYTES = 2 * 1024 * 1024  # contrato v1


def recortar(imagen: np.ndarray, zona: Zona, margen: float = 0.10) -> Optional[np.ndarray]:
    alto, ancho = imagen.shape[:2]
    x0, y0, x1, y1 = zona.caja_px(ancho, alto, margen)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return imagen[y0:y1, x0:x1].copy()


def a_jpeg(recorte: np.ndarray) -> Optional[bytes]:
    calidad = CALIDAD_JPEG
    while calidad >= 40:
        ok, buffer = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, calidad])
        if not ok:
            return None
        datos = buffer.tobytes()
        if len(datos) <= MAX_BYTES:
            return datos
        calidad -= 15
    return None

"""Objetos de datos que viajan entre las etapas de la canalización."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np

GASA = "gasa"
RECIPIENTE_ROJO = "recipiente_rojo"
RECIPIENTE_COMUN = "recipiente_comun"
CLASES = (GASA, RECIPIENTE_ROJO, RECIPIENTE_COMUN)
# Clase opcional: si el modelo la tiene, se activa el disparador por mano.
MANO = "mano"
# Con el detector compuesto: el modelo de tachos dice «recipiente» y el color decide si es
# rojo o común; las personas vienen del YOLO de COCO.
RECIPIENTE = "recipiente"
PERSONA = "persona"

ROJO = "rojo"
COMUN = "comun"
VEREDICTO = {ROJO: "conforme", COMUN: "no_conforme"}


@dataclass
class Fotograma:
    """Fotograma normalizado (640 × 480 por defecto) con su marca de tiempo.

    ``imagen`` es la versión reducida, sin deformar: si la cámara entrega otra proporción
    (16:9 en un teléfono), se escala para que quepa y se rellena con bandas negras.
    ``original`` es la imagen tal como la entregó la cámara; ``escala``, ``dx`` y ``dy``
    describen cómo se pasó de una a otra, para llevar cajas al original (etapa 2).
    """

    imagen: np.ndarray
    t: float                 # segundos monótonos (o tiempo del video, si es un archivo)
    momento: datetime        # hora real con zona horaria, para fechar el evento
    indice: int = 0
    original: Optional[np.ndarray] = field(default=None, repr=False)
    escala: float = 1.0      # píxeles de «imagen» por píxel del original
    dx: int = 0              # banda negra a la izquierda, en píxeles de «imagen»
    dy: int = 0              # banda negra arriba, en píxeles de «imagen»

    def caja_en_original(self, x0: float, y0: float, x1: float,
                         y1: float) -> tuple[int, int, int, int]:
        """Lleva una caja del fotograma reducido a píxeles del original, recortada a sus
        bordes. Sin original, devuelve la misma caja dentro de ``imagen``."""
        base = self.original if self.original is not None else self.imagen
        alto, ancho = base.shape[:2]
        escala = self.escala if self.original is not None else 1.0
        dx, dy = (self.dx, self.dy) if self.original is not None else (0, 0)

        def a_original(v: float, desplazamiento: int, limite: int) -> int:
            return int(round(min(max((v - desplazamiento) / escala, 0), limite)))

        return (a_original(x0, dx, ancho), a_original(y0, dy, alto),
                a_original(x1, dx, ancho), a_original(y1, dy, alto))

    @property
    def alto(self) -> int:
        return int(self.imagen.shape[0])

    @property
    def ancho(self) -> int:
        return int(self.imagen.shape[1])


@dataclass(frozen=True)
class Deteccion:
    clase: str
    confianza: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def centro(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


@dataclass
class EventoDescarte:
    """Evento confirmado, listo para publicarse según el contrato v1."""

    id_externo: str
    box: str
    recipiente: str
    confianza: float
    ocurrido_en: datetime
    modelo: str
    rasgos: dict[str, Any] = field(default_factory=dict)
    evidencia_jpeg: Optional[bytes] = None

    @property
    def veredicto(self) -> str:
        return VEREDICTO[self.recipiente]

    def como_payload(self) -> dict[str, Any]:
        import base64

        cuerpo: dict[str, Any] = {
            "id_externo": self.id_externo,
            "box": self.box,
            "recipiente": self.recipiente,
            "veredicto": self.veredicto,
            "confianza": round(float(self.confianza), 3),
            "ocurrido_en": self.ocurrido_en.isoformat(timespec="milliseconds"),
            "modelo": self.modelo[:40],
            "rasgos": self.rasgos,
        }
        if self.evidencia_jpeg:
            cuerpo["evidencia_jpeg_b64"] = base64.b64encode(self.evidencia_jpeg).decode("ascii")
        return cuerpo


def id_externo_para(box: str, momento: datetime) -> str:
    """``box2-20261027T104218.331-05:00``: el formato sugerido por el contrato v1."""
    ms = momento.microsecond // 1000
    zona = momento.isoformat()[-6:] if momento.utcoffset() is not None else ""
    return f"{box.replace('-', '')}-{momento:%Y%m%dT%H%M%S}.{ms:03d}{zona}"

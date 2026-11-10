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

ROJO = "rojo"
COMUN = "comun"
VEREDICTO = {ROJO: "conforme", COMUN: "no_conforme"}


@dataclass
class Fotograma:
    """Fotograma normalizado (640 × 480 por defecto) con su marca de tiempo."""

    imagen: np.ndarray
    t: float                 # segundos monótonos (o tiempo del video, si es un archivo)
    momento: datetime        # hora real con zona horaria, para fechar el evento
    indice: int = 0

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

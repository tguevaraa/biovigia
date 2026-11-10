"""Zonas de las bocas de los recipientes (M1, RF-01).

Los polígonos están normalizados entre 0 y 1 sobre el fotograma normalizado, igual que los
guarda el servidor. Este módulo no depende de OpenCV para poder probarse aislado.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .tipos import COMUN, ROJO

log = logging.getLogger("vision.zonas")
TIPOS = (ROJO, COMUN)


@dataclass(frozen=True)
class Zona:
    tipo: str
    puntos: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS:
            raise ValueError(f"Tipo de zona no válido: {self.tipo}")
        if len(self.puntos) < 3:
            raise ValueError(f"La zona {self.tipo} necesita al menos 3 puntos")

    def contiene(self, x: float, y: float) -> bool:
        """Prueba de contención por trazado de rayos (coordenadas normalizadas)."""
        dentro = False
        n = len(self.puntos)
        j = n - 1
        for i in range(n):
            xi, yi = self.puntos[i]
            xj, yj = self.puntos[j]
            if (yi > y) != (yj > y):
                cruce = (xj - xi) * (y - yi) / (yj - yi) + xi
                if x < cruce:
                    dentro = not dentro
            j = i
        return dentro

    @property
    def area(self) -> float:
        total = 0.0
        pts = self.puntos
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            total += x1 * y2 - x2 * y1
        return abs(total) / 2

    def caja_px(self, ancho: int, alto: int, margen: float = 0.10) -> tuple[int, int, int, int]:
        """Rectángulo que envuelve el polígono, con margen, en píxeles y dentro del cuadro."""
        xs = [p[0] for p in self.puntos]
        ys = [p[1] for p in self.puntos]
        mx = (max(xs) - min(xs)) * margen
        my = (max(ys) - min(ys)) * margen
        x0 = max(0, int((min(xs) - mx) * ancho))
        y0 = max(0, int((min(ys) - my) * alto))
        x1 = min(ancho, int(round((max(xs) + mx) * ancho)))
        y1 = min(alto, int(round((max(ys) + my) * alto)))
        return x0, y0, x1, y1

    def puntos_px(self, ancho: int, alto: int) -> list[tuple[int, int]]:
        return [(int(x * ancho), int(y * alto)) for x, y in self.puntos]


class ConjuntoZonas:
    """Las zonas de un box. Si dos se solapan, gana la de menor área (la más específica)."""

    def __init__(self, zonas: Iterable[Zona] = ()) -> None:
        self._zonas = {z.tipo: z for z in zonas}

    def __bool__(self) -> bool:
        return bool(self._zonas)

    def __iter__(self):
        return iter(self._zonas.values())

    def __len__(self) -> int:
        return len(self._zonas)

    def get(self, tipo: str) -> Optional[Zona]:
        return self._zonas.get(tipo)

    @property
    def completas(self) -> bool:
        return all(t in self._zonas for t in TIPOS)

    def zona_de(self, x: float, y: float) -> Optional[str]:
        candidatas = [z for z in self._zonas.values() if z.contiene(x, y)]
        if not candidatas:
            return None
        return min(candidatas, key=lambda z: z.area).tipo

    def como_dict(self) -> dict[str, list[list[float]] | None]:
        return {t: ([list(p) for p in z.puntos] if (z := self._zonas.get(t)) else None)
                for t in TIPOS}

    @classmethod
    def desde_dict(cls, datos: dict) -> "ConjuntoZonas":
        zonas = []
        for tipo in TIPOS:
            puntos = (datos or {}).get(tipo)
            if puntos:
                try:
                    zonas.append(Zona(tipo, tuple((float(x), float(y)) for x, y in puntos)))
                except (ValueError, TypeError) as exc:
                    log.warning("Zona %s ignorada: %s", tipo, exc)
        return cls(zonas)

    @classmethod
    def cargar(cls, ruta: Path) -> "ConjuntoZonas":
        if not ruta.exists():
            return cls()
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("No se pudo leer %s: %s", ruta, exc)
            return cls()
        return cls.desde_dict(datos.get("zonas", datos))

    def guardar(self, ruta: Path, box: str) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        cuerpo = {"box": box, "zonas": self.como_dict(),
                  "nota": "Coordenadas normalizadas entre 0 y 1 sobre el fotograma de 640x480."}
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(cuerpo, indent=2, ensure_ascii=False), encoding="utf-8")
        temporal.replace(ruta)

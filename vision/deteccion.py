"""M2 · Detección de la gasa o torunda y de los dos recipientes.

Dos implementaciones con la misma interfaz:

* ``DetectorYOLO``: el modelo entrenado con el conjunto de datos propio (OE1, OE2). Se carga
  una sola vez por proceso (Singleton, Tabla 39).
* ``DetectorMovimiento``: detector de desarrollo, sin modelo, que encuentra objetos blancos
  en movimiento (sustracción de fondo + color). Sirve para probar el sistema de extremo a
  extremo con la cámara mientras el modelo no está entrenado. **No es el detector del
  informe** y su nombre de modelo lo deja claro en cada evento.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .tipos import CLASES, GASA, RECIPIENTE_COMUN, RECIPIENTE_ROJO, Deteccion

log = logging.getLogger("vision.deteccion")

# Nombres de clase que se aceptan en el modelo entrenado, por si el conjunto de datos se
# anotó con otra grafía.
ALIAS = {
    "gasa": GASA, "torunda": GASA, "gasa_torunda": GASA, "gasa_o_torunda": GASA,
    "algodon": GASA, "algodón": GASA,
    "recipiente_rojo": RECIPIENTE_ROJO, "rojo": RECIPIENTE_ROJO, "tacho_rojo": RECIPIENTE_ROJO,
    "recipiente_comun": RECIPIENTE_COMUN, "comun": RECIPIENTE_COMUN,
    "recipiente_común": RECIPIENTE_COMUN, "común": RECIPIENTE_COMUN,
    "recipiente_negro": RECIPIENTE_COMUN, "negro": RECIPIENTE_COMUN,
    "tacho_negro": RECIPIENTE_COMUN,
}


class ErrorModelo(RuntimeError):
    """El modelo no existe o no tiene las clases de BioVigIA."""


class Detector(Protocol):
    nombre: str
    umbral: float

    def detectar(self, imagen: np.ndarray) -> list[Deteccion]: ...


def _normalizar_nombre(nombre: str) -> str:
    return nombre.strip().lower().replace(" ", "_").replace("-", "_")


class DetectorYOLO:
    _instancias: dict[str, "DetectorYOLO"] = {}
    _candado = threading.Lock()

    def __init__(self, ruta: Path, umbral: float, imgsz: int = 640) -> None:
        if not Path(ruta).exists():
            raise ErrorModelo(
                f"No existe el modelo {ruta}. Entrénalo con herramientas/entrenar_modelo.py o "
                "usa --detector movimiento para probar sin modelo.")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ErrorModelo("Falta ultralytics: pip install -r requirements-vision.txt") from exc
        self.modelo = YOLO(str(ruta))
        self.nombre = Path(ruta).stem
        self.umbral = umbral
        self.imgsz = imgsz
        nombres = getattr(self.modelo, "names", {}) or {}
        self.mapa = {int(i): ALIAS.get(_normalizar_nombre(n)) for i, n in nombres.items()}
        if GASA not in self.mapa.values():
            raise ErrorModelo(
                f"El modelo {Path(ruta).name} no tiene la clase 'gasa' (clases: "
                f"{', '.join(map(str, nombres.values()))}). Un yolov8n.pt sin ajustar detecta "
                "objetos de COCO, no gasas: usa los pesos entrenados con datos/dataset.yaml.")
        faltan = [c for c in CLASES if c not in self.mapa.values()]
        if faltan:
            log.warning("El modelo no tiene las clases %s; la verificación de alineación de "
                        "zonas queda desactivada.", ", ".join(faltan))
        log.info("Modelo %s cargado (%s clases)", self.nombre, len(nombres))

    @classmethod
    def obtener(cls, ruta: Path, umbral: float, imgsz: int = 640) -> "DetectorYOLO":
        """Singleton por ruta: el modelo se carga una sola vez en memoria."""
        clave = str(Path(ruta).resolve())
        with cls._candado:
            if clave not in cls._instancias:
                cls._instancias[clave] = cls(ruta, umbral, imgsz)
            instancia = cls._instancias[clave]
            instancia.umbral = umbral
            return instancia

    def detectar(self, imagen: np.ndarray) -> list[Deteccion]:
        # El umbral del predictor es bajo a propósito: el filtro definitivo lo aplica el
        # motor de reglas, para que el umbral se pueda cambiar en caliente (RNF-16).
        resultado = self.modelo.predict(imagen, conf=min(self.umbral, 0.25), imgsz=self.imgsz,
                                        verbose=False)[0]
        detecciones: list[Deteccion] = []
        cajas = getattr(resultado, "boxes", None)
        if cajas is None or len(cajas) == 0:
            return detecciones
        xyxy = cajas.xyxy.cpu().numpy()
        conf = cajas.conf.cpu().numpy()
        cls_ = cajas.cls.cpu().numpy().astype(int)
        for (x0, y0, x1, y1), c, k in zip(xyxy, conf, cls_):
            clase = self.mapa.get(int(k))
            if clase is not None:
                detecciones.append(Deteccion(clase, float(c), float(x0), float(y0),
                                             float(x1), float(y1)))
        return detecciones


class DetectorMovimiento:
    """Objetos claros y poco saturados que se mueven sobre un fondo aprendido."""

    def __init__(self, umbral: float = 0.5, area_min: int = 120, area_max: int = 25000) -> None:
        self.nombre = "dev-movimiento-v0"
        self.umbral = umbral
        self.area_min, self.area_max = area_min, area_max
        self.fondo = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32,
                                                        detectShadows=False)
        self.nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def detectar(self, imagen: np.ndarray) -> list[Deteccion]:
        primer_plano = self.fondo.apply(imagen)
        hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
        blanco = cv2.inRange(hsv, (0, 0, 150), (180, 70, 255))
        mascara = cv2.bitwise_and(primer_plano, blanco)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, self.nucleo)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, self.nucleo, iterations=2)
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detecciones = []
        for c in contornos:
            area = cv2.contourArea(c)
            if not self.area_min <= area <= self.area_max:
                continue
            x, y, w, h = cv2.boundingRect(c)
            relleno = area / float(w * h) if w and h else 0.0
            confianza = float(min(0.99, 0.45 + 0.5 * relleno))
            detecciones.append(Deteccion(GASA, confianza, x, y, x + w, y + h))
        return detecciones


def crear_detector(tipo: str, ruta_modelo: Path, umbral: float, imgsz: int = 640) -> Detector:
    if tipo == "movimiento":
        log.warning("Usando el detector de DESARROLLO por movimiento. Los eventos llevarán el "
                    "modelo 'dev-movimiento-v0'. Para la prueba de aceptación usa el modelo "
                    "entrenado (--detector yolo).")
        return DetectorMovimiento(umbral)
    return DetectorYOLO.obtener(ruta_modelo, umbral, imgsz)

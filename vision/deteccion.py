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

from .tipos import (CLASES, GASA, MANO, PERSONA, RECIPIENTE, RECIPIENTE_COMUN, RECIPIENTE_ROJO,
                    Deteccion)

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
    "mano": MANO, "antebrazo": MANO, "brazo": MANO, "mano_antebrazo": MANO,
}


class ErrorModelo(RuntimeError):
    """El modelo no se puede usar: no existe, falta ultralytics o no tiene las clases.

    Guarda el ``motivo`` (``"no_existe"``, ``"sin_ultralytics"`` o ``"sin_clase_gasa"``) y
    la ``ruta`` del modelo para que quien la captura decida qué hacer sin leer el texto.
    Los mensajes se crean con los métodos de clase, así quedan todos en un solo lugar.
    """

    NO_EXISTE = "no_existe"
    SIN_ULTRALYTICS = "sin_ultralytics"
    SIN_CLASE_GASA = "sin_clase_gasa"

    def __init__(self, mensaje: str, motivo: str, ruta: Path | None = None) -> None:
        super().__init__(mensaje)
        self.motivo = motivo
        self.ruta = ruta

    @classmethod
    def no_existe(cls, ruta: Path) -> "ErrorModelo":
        return cls(f"No existe el modelo {ruta}. Entrénalo con herramientas/entrenar_modelo.py "
                   "o usa --detector movimiento para probar sin modelo.", cls.NO_EXISTE, ruta)

    @classmethod
    def sin_ultralytics(cls, ruta: Path) -> "ErrorModelo":
        return cls("Falta ultralytics: pip install -r requirements-vision.txt",
                   cls.SIN_ULTRALYTICS, ruta)

    @classmethod
    def sin_clase_gasa(cls, ruta: Path, clases: list[str]) -> "ErrorModelo":
        return cls(f"El modelo {ruta.name} no tiene la clase 'gasa' (clases: "
                   f"{', '.join(clases)}). Un yolov8n.pt sin ajustar detecta objetos de COCO, "
                   "no gasas: usa los pesos entrenados con datos/dataset.yaml.",
                   cls.SIN_CLASE_GASA, ruta)


class Detector(Protocol):
    nombre: str
    umbral: float
    detecta_mano: bool

    def detectar(self, imagen: np.ndarray) -> list[Deteccion]: ...


def _normalizar_nombre(nombre: str) -> str:
    return nombre.strip().lower().replace(" ", "_").replace("-", "_")


class DetectorYOLO:
    _instancias: dict[str, "DetectorYOLO"] = {}
    _candado = threading.Lock()

    def __init__(self, ruta: Path, umbral: float, imgsz: int = 640) -> None:
        ruta = Path(ruta)
        if not ruta.exists():
            raise ErrorModelo.no_existe(ruta)
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ErrorModelo.sin_ultralytics(ruta) from exc
        self.modelo = YOLO(str(ruta))
        self.nombre = ruta.stem
        self.umbral = umbral
        self.imgsz = imgsz
        nombres = getattr(self.modelo, "names", {}) or {}
        self.mapa = {int(i): ALIAS.get(_normalizar_nombre(n)) for i, n in nombres.items()}
        if GASA not in self.mapa.values():
            raise ErrorModelo.sin_clase_gasa(ruta, [str(n) for n in nombres.values()])
        faltan = [c for c in CLASES if c not in self.mapa.values()]
        if faltan:
            log.warning("El modelo no tiene las clases %s; la verificación de alineación de "
                        "zonas queda desactivada.", ", ".join(faltan))
        self.detecta_mano = MANO in self.mapa.values()
        log.info("Modelo %s cargado (%s clases%s)", self.nombre, len(nombres),
                 ", con clase mano" if self.detecta_mano else "")

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

    # Piel en YCrCb. Aproximación de desarrollo: no distingue una mano de otro objeto de
    # tono parecido que se mueva. El disparador real usa la clase «mano» del modelo.
    PIEL_MIN, PIEL_MAX = (0, 135, 85), (255, 180, 135)
    AREA_MANO_MIN = 1500

    def __init__(self, umbral: float = 0.5, area_min: int = 120, area_max: int = 25000,
                 detectar_mano: bool = False) -> None:
        self.nombre = "dev-movimiento-v0"
        self.umbral = umbral
        self.detecta_mano = detectar_mano
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
        if self.detecta_mano:
            detecciones += self._manos(imagen, primer_plano)
        return detecciones

    def _manos(self, imagen: np.ndarray, primer_plano: np.ndarray) -> list[Deteccion]:
        """Regiones grandes de tono piel que se mueven."""
        ycrcb = cv2.cvtColor(imagen, cv2.COLOR_BGR2YCrCb)
        piel = cv2.inRange(ycrcb, self.PIEL_MIN, self.PIEL_MAX)
        mascara = cv2.bitwise_and(primer_plano, piel)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, self.nucleo)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, self.nucleo, iterations=3)
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        manos = []
        for c in contornos:
            area = cv2.contourArea(c)
            if area < self.AREA_MANO_MIN:
                continue
            x, y, w, h = cv2.boundingRect(c)
            relleno = area / float(w * h) if w and h else 0.0
            manos.append(Deteccion(MANO, float(min(0.99, 0.5 + 0.5 * relleno)),
                                   x, y, x + w, y + h))
        return manos


def fraccion_roja(imagen: np.ndarray, d: Deteccion) -> float:
    """Parte de la caja (sin los bordes) con tono rojo saturado: decide si un tacho es el
    rojo (residuos biocontaminados) o el común."""
    x0, y0, x1, y1 = (int(round(v)) for v in (d.x0, d.y0, d.x1, d.y1))
    mx, my = (x1 - x0) // 6, (y1 - y0) // 6
    recorte = imagen[max(0, y0 + my):max(0, y1 - my), max(0, x0 + mx):max(0, x1 - mx)]
    if recorte.size == 0:
        return 0.0
    hsv = cv2.cvtColor(recorte, cv2.COLOR_BGR2HSV)
    rojo = cv2.inRange(hsv, (0, 90, 60), (10, 255, 255)) | cv2.inRange(hsv, (170, 90, 60),
                                                                         (180, 255, 255))
    return float(np.count_nonzero(rojo)) / rojo.size


class ParteYOLO:
    """Un modelo YOLO de una sola tarea dentro del detector compuesto.

    ``clase`` es el nombre que reciben TODAS sus detecciones (el modelo de gasas → «gasa»,
    el de tachos → «recipiente», el de COCO → «persona»); ``clases_coco`` limita qué clases
    del modelo se usan (en COCO, la 0 es «person»)."""

    def __init__(self, ruta: Path, clase: str | None, imgsz: int = 640,
                 clases_coco: list[int] | None = None) -> None:
        ruta = Path(ruta)
        if not ruta.exists():
            raise ErrorModelo.no_existe(ruta)
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ErrorModelo.sin_ultralytics(ruta) from exc
        self.modelo = YOLO(str(ruta))
        self.nombre = ruta.stem
        # Sin clase fija (tubos, jeringas…): la que diga el modelo, que tiene una sola.
        self.clase = clase or str(self.modelo.names[0])
        self.imgsz = imgsz
        self.clases_coco = clases_coco

    def detectar(self, imagen: np.ndarray, conf: float) -> list[Deteccion]:
        r = self.modelo.predict(imagen, conf=conf, imgsz=self.imgsz, classes=self.clases_coco,
                                verbose=False)[0]
        cajas = getattr(r, "boxes", None)
        if cajas is None or len(cajas) == 0:
            return []
        return [Deteccion(self.clase, float(c), float(x0), float(y0), float(x1), float(y1))
                for (x0, y0, x1, y1), c in zip(cajas.xyxy.cpu().numpy(), cajas.conf.cpu().numpy())]


class DetectorCompuesto:
    """Varios modelos de una tarea cada uno, que se corren sobre el mismo fotograma.

    Así cada objeto se entrena por separado (gasas, tachos y, más adelante, jeringas o
    curitas) y no hace falta un conjunto de datos con todo anotado junto. Los tachos se
    reconocen en cada fotograma, sin polígonos fijos: si alguien mueve uno, la zona lo
    sigue (vision/zonas_dinamicas.py). El tipo de tacho lo decide el color.
    """

    detecta_mano = False

    def __init__(self, partes: list, umbral: float, umbral_rojo: float = 0.25,
                 residuos: tuple[str, ...] = (GASA,)) -> None:
        self.partes = partes
        # Clases que las reglas siguen como residuo (la gasa y los objetos extra).
        self.residuos = residuos
        self.umbral = umbral
        self.umbral_rojo = umbral_rojo
        if not any(p.clase == GASA for p in partes):
            raise ErrorModelo("El detector compuesto necesita un modelo de gasas "
                              "(BIOVIGIA_MODELO_GASAS).", ErrorModelo.SIN_CLASE_GASA)
        log.info("Detector compuesto: %s", ", ".join(f"{p.nombre} → {p.clase}" for p in partes))

    @classmethod
    def desde_rutas(cls, gasas: Path, tachos: Path | None, personas: Path | None,
                    umbral: float, imgsz: int = 640, umbral_rojo: float = 0.25,
                    objetos: tuple[Path, ...] = ()) -> "DetectorCompuesto":
        partes = [ParteYOLO(gasas, GASA, imgsz)]
        # Otros residuos (tubos, jeringas…): un modelo de una clase cada uno.
        extra = [ParteYOLO(ruta, None, imgsz) for ruta in objetos]
        partes += extra
        if tachos:
            partes.append(ParteYOLO(tachos, RECIPIENTE, imgsz))
        else:
            log.warning("Sin modelo de tachos (BIOVIGIA_MODELO_TACHOS): no habrá zonas, así "
                        "que no se podrán confirmar descartes.")
        if personas and Path(personas).exists():
            partes.append(ParteYOLO(personas, PERSONA, imgsz, clases_coco=[0]))
        elif personas:
            log.warning("No existe el modelo de personas %s; se sigue sin él.", personas)
        return cls(partes, umbral, umbral_rojo,
                   residuos=(GASA, *dict.fromkeys(p.clase for p in extra)))

    @property
    def nombre(self) -> str:
        return "+".join(p.nombre.removeprefix("biovigia-") for p in self.partes)

    def detectar(self, imagen: np.ndarray) -> list[Deteccion]:
        # Como en DetectorYOLO, el filtro final lo hacen las reglas (umbral en caliente).
        conf = min(self.umbral, 0.15)
        detecciones: list[Deteccion] = []
        for parte in self.partes:
            for d in parte.detectar(imagen, conf):
                if d.clase == RECIPIENTE:
                    rojo = fraccion_roja(imagen, d) >= self.umbral_rojo
                    d = Deteccion(RECIPIENTE_ROJO if rojo else RECIPIENTE_COMUN, d.confianza,
                                  d.x0, d.y0, d.x1, d.y1)
                detecciones.append(d)
        return detecciones


def crear_detector(tipo: str, ruta_modelo: Path, umbral: float, imgsz: int = 640,
                   detectar_mano: bool = False, compuesto: dict | None = None) -> Detector:
    if tipo == "compuesto":
        c = compuesto or {}
        return DetectorCompuesto.desde_rutas(c.get("gasas") or ruta_modelo, c.get("tachos"),
                                             c.get("personas"), umbral, imgsz,
                                             c.get("umbral_rojo", 0.25),
                                             tuple(c.get("objetos") or ()))
    if tipo == "movimiento":
        log.warning("Usando el detector de DESARROLLO por movimiento. Los eventos llevarán el "
                    "modelo 'dev-movimiento-v0'. Para la prueba de aceptación usa el modelo "
                    "entrenado (--detector yolo).")
        return DetectorMovimiento(umbral, detectar_mano=detectar_mano)
    return DetectorYOLO.obtener(ruta_modelo, umbral, imgsz)

"""M1 · Captura y normalización del video.

Aísla al resto del sistema de las particularidades de la cámara: entrega fotogramas de
640 × 480 a la frecuencia de muestreo configurada, mide los fps reales y se reconecta sola
si la cámara se cae. No persiste video (RNF-02).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import cv2
import numpy as np

from .tipos import Fotograma

log = logging.getLogger("vision.captura")


def normalizar(imagen: np.ndarray, ancho: int, alto: int) -> np.ndarray:
    if imagen.ndim == 2:
        imagen = cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR)
    if imagen.shape[1] == ancho and imagen.shape[0] == alto:
        return imagen
    return cv2.resize(imagen, (ancho, alto), interpolation=cv2.INTER_AREA)


def abrir_captura(fuente: str) -> cv2.VideoCapture:
    """Abre una cámara USB por índice, un archivo o un flujo RTSP/HTTP."""
    if fuente.isdigit():
        indice = int(fuente)
        if os.name == "nt":  # en Windows DirectShow abre mucho más rápido que MSMF
            cap = cv2.VideoCapture(indice, cv2.CAP_DSHOW)
            if cap.isOpened():
                return cap
            cap.release()
        return cv2.VideoCapture(indice)
    if fuente.startswith("rtsp://"):
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        cap = cv2.VideoCapture(fuente, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    return cv2.VideoCapture(fuente)


def listar_camaras(maximo: int = 6) -> list[tuple[int, int, int]]:
    """Índices de cámara que entregan imagen, con su resolución: [(indice, ancho, alto)]."""
    encontradas = []
    for indice in range(maximo):
        cap = abrir_captura(str(indice))
        try:
            if not cap.isOpened():
                continue
            ok, imagen = cap.read()
            if ok and imagen is not None:
                encontradas.append((indice, int(imagen.shape[1]), int(imagen.shape[0])))
        finally:
            cap.release()
    return encontradas


class MedidorFps:
    """Fotogramas por segundo realmente entregados, con media móvil exponencial."""

    def __init__(self, alfa: float = 0.1) -> None:
        self.alfa = alfa
        self.valor: Optional[float] = None
        self._previo: Optional[float] = None

    def marcar(self, t: float) -> None:
        if self._previo is not None and t > self._previo:
            instantaneo = 1.0 / (t - self._previo)
            self.valor = instantaneo if self.valor is None else (
                self.alfa * instantaneo + (1 - self.alfa) * self.valor)
        self._previo = t

    def reiniciar(self) -> None:
        self.valor = None
        self._previo = None


class FuenteVideo:
    """Interfaz común. ``leer`` devuelve un fotograma, o ``None`` si no hay (o terminó)."""

    terminada = False
    conectada = False

    def __init__(self, ancho: int, alto: int, fps: int) -> None:
        self.ancho, self.alto = ancho, alto
        self.fps = fps
        self.medidor = MedidorFps()

    @property
    def fps_medido(self) -> Optional[float]:
        return self.medidor.valor

    def cambiar_fps(self, fps: int) -> None:
        """Aplica una nueva frecuencia de muestreo enviada desde PAN-10."""
        self.fps = max(1, int(fps))

    def leer(self) -> Optional[Fotograma]:  # pragma: no cover - interfaz
        raise NotImplementedError

    def cerrar(self) -> None:  # pragma: no cover - interfaz
        pass


class FuenteArchivo(FuenteVideo):
    """Video grabado. El tiempo es el del video, así la evaluación es reproducible."""

    def __init__(self, ruta: str, ancho: int, alto: int, fps: int,
                 inicio: Optional[datetime] = None) -> None:
        super().__init__(ancho, alto, fps)
        self.ruta = ruta
        self.cap = cv2.VideoCapture(ruta)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se puede abrir el video {ruta}")
        self.fps_origen = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.paso = max(1.0, self.fps_origen / max(1, fps))
        self._siguiente = 0.0
        self._indice = -1
        # El video ya ocurrió: se ancla para que termine «ahora» y ningún evento quede en el
        # futuro (el servidor rechaza fechas futuras).
        self.inicio = inicio or (
            datetime.now().astimezone() - timedelta(seconds=self.duracion_s))
        self.conectada = True

    def leer(self) -> Optional[Fotograma]:
        while True:
            ok, imagen = self.cap.read()
            if not ok:
                self.terminada = True
                self.conectada = False
                return None
            self._indice += 1
            if self._indice + 1e-6 < self._siguiente:
                continue
            self._siguiente += self.paso
            t = self._indice / self.fps_origen
            self.medidor.marcar(t)
            return Fotograma(normalizar(imagen, self.ancho, self.alto), t,
                             self.inicio + timedelta(seconds=t), self._indice)

    def cambiar_fps(self, fps: int) -> None:
        super().cambiar_fps(fps)
        self.paso = max(1.0, self.fps_origen / self.fps)

    @property
    def duracion_s(self) -> float:
        total = self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        return total / self.fps_origen if self.fps_origen else 0.0

    def cerrar(self) -> None:
        self.cap.release()


class FuenteEnVivo(FuenteVideo):
    """Cámara USB o RTSP. Un hilo lee sin parar y conserva solo el último fotograma, así
    el retraso no se acumula aunque el detector sea más lento que la cámara."""

    REINTENTO_S = 2.0
    SIN_FOTOGRAMA_S = 3.0  # sin fotogramas nuevos por este tiempo = cámara caída

    def __init__(self, fuente: str, ancho: int, alto: int, fps: int) -> None:
        super().__init__(ancho, alto, fps)
        self.fuente = fuente
        self._cap: Optional[cv2.VideoCapture] = None
        self._ultimo: Optional[np.ndarray] = None
        self._ultimo_t = 0.0
        self._entregado_t = 0.0
        self._indice = 0
        self._candado = threading.Lock()
        self._activo = True
        self._hilo = threading.Thread(target=self._bucle, name="captura", daemon=True)
        self._hilo.start()

    def _abrir(self) -> bool:
        cap = abrir_captura(self.fuente)
        if not cap.isOpened():
            cap.release()
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.ancho)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.alto)
        self._cap = cap
        log.info("Cámara %s conectada", self.fuente)
        return True

    def _bucle(self) -> None:
        while self._activo:
            if self._cap is None and not self._abrir():
                self._marcar_caida("no se pudo abrir")
                time.sleep(self.REINTENTO_S)
                continue
            ok, imagen = self._cap.read()
            if not ok or imagen is None:
                self._marcar_caida("dejó de entregar fotogramas")
                self._cap.release()
                self._cap = None
                time.sleep(self.REINTENTO_S)
                continue
            with self._candado:
                self._ultimo = imagen
                self._ultimo_t = time.monotonic()
                self.conectada = True

    def _marcar_caida(self, motivo: str) -> None:
        if self.conectada:
            log.warning("Cámara %s desconectada: %s", self.fuente, motivo)
        self.conectada = False
        self.medidor.reiniciar()

    def leer(self) -> Optional[Fotograma]:
        """Espera al siguiente instante de muestreo y devuelve el fotograma más reciente."""
        periodo = 1.0 / max(1, self.fps)
        espera = self._entregado_t + periodo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        with self._candado:
            imagen, t_img = self._ultimo, self._ultimo_t
        ahora = time.monotonic()
        if imagen is None or ahora - t_img > self.SIN_FOTOGRAMA_S:
            if imagen is not None and self.conectada:
                self._marcar_caida("sin fotogramas nuevos")
            time.sleep(0.2)
            return None
        self._entregado_t = ahora
        self._indice += 1
        self.medidor.marcar(ahora)
        return Fotograma(normalizar(imagen, self.ancho, self.alto), ahora,
                         datetime.now().astimezone(), self._indice)

    def cerrar(self) -> None:
        self._activo = False
        self._hilo.join(timeout=3)
        if self._cap is not None:
            self._cap.release()


def crear_fuente(fuente: str, ancho: int, alto: int, fps: int) -> FuenteVideo:
    es_archivo = not fuente.isdigit() and "://" not in fuente
    if es_archivo:
        return FuenteArchivo(fuente, ancho, alto, fps)
    return FuenteEnVivo(fuente, ancho, alto, fps)

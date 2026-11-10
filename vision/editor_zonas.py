"""Editor local de zonas con OpenCV (alternativa a PAN-09 cuando no hay servidor).

Clic izquierdo: añadir punto · clic derecho o Retroceso: quitar el último
R / C: elegir recipiente rojo o común · S: guardar · Q o Esc: salir sin guardar

Las zonas del servidor (PAN-09) tienen prioridad: este archivo se usa solo si el servidor
no tiene zonas para el box o no está disponible.
"""
from __future__ import annotations

import logging
import time

import cv2
import numpy as np

from .captura import crear_fuente
from .configuracion import Configuracion
from .pipeline import COLOR_ZONA, NOMBRE_ZONA
from .tipos import COMUN, ROJO
from .zonas import ConjuntoZonas, Zona

log = logging.getLogger("vision.editor")
VENTANA = "BioVigIA - editor de zonas"


def capturar_referencia(config: Configuracion, calentamiento_s: float = 2.0) -> np.ndarray:
    """Toma un fotograma normalizado de la fuente, dejando que la cámara ajuste la exposición."""
    fuente = crear_fuente(config.fuente, config.ancho, config.alto, config.parametros.fps_muestreo)
    try:
        limite = time.monotonic() + max(calentamiento_s, 0) + 10
        inicio = time.monotonic()
        ultimo = None
        while time.monotonic() < limite:
            f = fuente.leer()
            if f is not None:
                ultimo = f
                if time.monotonic() - inicio >= calentamiento_s or fuente.terminada:
                    break
            elif fuente.terminada:
                break
        if ultimo is None:
            raise RuntimeError(f"La fuente {config.fuente} no entregó ningún fotograma")
        return ultimo.imagen
    finally:
        fuente.cerrar()


def editar(config: Configuracion) -> bool:
    imagen = capturar_referencia(config)
    zonas = ConjuntoZonas.cargar(config.archivo_zonas)
    puntos = {t: (list(z.puntos) if (z := zonas.get(t)) else []) for t in (ROJO, COMUN)}
    estado = {"tipo": ROJO}
    alto, ancho = imagen.shape[:2]

    def al_clic(evento, x, y, *_):
        if evento == cv2.EVENT_LBUTTONDOWN:
            puntos[estado["tipo"]].append((round(x / ancho, 4), round(y / alto, 4)))
        elif evento == cv2.EVENT_RBUTTONDOWN and puntos[estado["tipo"]]:
            puntos[estado["tipo"]].pop()

    cv2.namedWindow(VENTANA)
    cv2.setMouseCallback(VENTANA, al_clic)
    while True:
        lienzo = imagen.copy()
        for tipo, lista in puntos.items():
            if not lista:
                continue
            pts = np.array([(int(x * ancho), int(y * alto)) for x, y in lista], dtype=np.int32)
            grosor = 3 if tipo == estado["tipo"] else 1
            cv2.polylines(lienzo, [pts], len(lista) >= 3, COLOR_ZONA[tipo], grosor)
            for p in pts:
                cv2.circle(lienzo, tuple(int(v) for v in p), 4, COLOR_ZONA[tipo], -1)
        texto = (f"Trazando: {NOMBRE_ZONA[estado['tipo']]} ({len(puntos[estado['tipo']])} pts) "
                 "| R/C cambiar | S guardar | Q salir")
        cv2.rectangle(lienzo, (0, 0), (ancho, 24), (20, 28, 40), -1)
        cv2.putText(lienzo, texto, (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1,
                    cv2.LINE_AA)
        cv2.imshow(VENTANA, lienzo)
        tecla = cv2.waitKey(30) & 0xFF
        if tecla in (ord("r"), ord("R")):
            estado["tipo"] = ROJO
        elif tecla in (ord("c"), ord("C")):
            estado["tipo"] = COMUN
        elif tecla == 8 and puntos[estado["tipo"]]:
            puntos[estado["tipo"]].pop()
        elif tecla in (ord("s"), ord("S")):
            nuevas = [Zona(t, tuple(p)) for t, p in puntos.items() if len(p) >= 3]
            if not nuevas:
                log.warning("Traza al menos un polígono de 3 puntos antes de guardar")
                continue
            ConjuntoZonas(nuevas).guardar(config.archivo_zonas, config.box)
            log.info("Zonas guardadas en %s", config.archivo_zonas)
            cv2.destroyWindow(VENTANA)
            return True
        elif tecla in (ord("q"), ord("Q"), 27):
            cv2.destroyWindow(VENTANA)
            return False

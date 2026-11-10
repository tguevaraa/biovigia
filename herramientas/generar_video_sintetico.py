#!/usr/bin/env python3
"""Genera videos sintéticos de la estación de descarte para probar sin cámara.

Dibuja un recipiente rojo y uno negro sobre fondo claro y una «gasa» blanca que cae en
uno de ellos, pasa cerca sin entrar, o no aparece. No reemplaza a los videos reales de
BVIA-32: sirve para probar la canalización con el detector de desarrollo.

    python herramientas/generar_video_sintetico.py --tipo comun --salida prueba_comun.mp4
    python herramientas/generar_video_sintetico.py --todos --carpeta datos/sinteticos
"""
from __future__ import annotations

import argparse
import json
import pathlib

import cv2
import numpy as np

ANCHO, ALTO, FPS = 640, 480, 30
# Bocas de los recipientes (x0, y0, x1, y1) en píxeles y como zonas normalizadas.
ROJO = (110, 230, 270, 330)
COMUN = (370, 230, 530, 330)


def zonas() -> dict:
    def poligono(caja):
        x0, y0, x1, y1 = caja
        return [[x0 / ANCHO, y0 / ALTO], [x1 / ANCHO, y0 / ALTO],
                [x1 / ANCHO, y1 / ALTO], [x0 / ANCHO, y1 / ALTO]]
    return {"rojo": poligono(ROJO), "comun": poligono(COMUN)}


def escena() -> np.ndarray:
    img = np.full((ALTO, ANCHO, 3), (205, 200, 195), np.uint8)      # pared clara
    cv2.rectangle(img, (0, 360), (ANCHO, ALTO), (170, 168, 165), -1)  # piso
    cv2.rectangle(img, (ROJO[0], ROJO[1]), (ROJO[2], 420), (40, 40, 200), -1)
    cv2.rectangle(img, (ROJO[0], ROJO[1]), (ROJO[2], ROJO[1] + 30), (30, 30, 150), -1)
    cv2.rectangle(img, (COMUN[0], COMUN[1]), (COMUN[2], 420), (35, 35, 35), -1)
    cv2.rectangle(img, (COMUN[0], COMUN[1]), (COMUN[2], COMUN[1] + 30), (20, 20, 20), -1)
    return img


def trayectoria(tipo: str, n: int) -> list[tuple[float, float] | None]:
    """Posición de la gasa en cada fotograma (None = no visible).

    La cámara mira desde arriba, así que la mano que se acerca a la boca, la suelta y la
    gasa que cae quedan dentro del polígono de la boca durante varios fotogramas.
    """
    puntos: list[tuple[float, float] | None] = [None] * n
    llegada, suelta = int(n * 0.25), int(n * 0.45)
    if tipo in ("rojo", "comun"):
        caja = ROJO if tipo == "rojo" else COMUN
        destino = ((caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2 - 15)
        origen = (destino[0] + 80, 50.0)
        for i in range(llegada, suelta):                 # la mano acerca la gasa
            a = (i - llegada) / (suelta - llegada)
            puntos[i] = (origen[0] + (destino[0] - origen[0]) * a,
                         origen[1] + (destino[1] - origen[1]) * a)
        for i in range(suelta, suelta + 12):             # sobre la boca, la suelta y cae
            puntos[i] = (destino[0] + (i - suelta) * 0.5, destino[1] + (i - suelta) * 2.5)
    elif tipo == "negativo":
        # Se acerca a la boca del común, la roza un instante, duda y se retira.
        fin = int(n * 0.85)
        for i in range(llegada, fin):
            a = (i - llegada) / (fin - llegada)
            puntos[i] = (450.0, float(60 + 190 * np.sin(np.pi * a)))
    return puntos


def generar(tipo: str, salida: pathlib.Path, segundos: float = 5.0, semilla: int = 0) -> None:
    rng = np.random.default_rng(semilla)
    n = int(segundos * FPS)
    base = escena()
    escritor = cv2.VideoWriter(str(salida), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (ANCHO, ALTO))
    if not escritor.isOpened():
        raise SystemExit(f"No se pudo crear {salida}")
    for p in trayectoria(tipo, n):
        cuadro = base.copy()
        if p is not None:
            cv2.ellipse(cuadro, (int(p[0]), int(p[1])), (14, 10), 15, 0, 360, (250, 250, 250), -1)
        ruido = rng.normal(0, 2.0, cuadro.shape).astype(np.int16)
        escritor.write(np.clip(cuadro.astype(np.int16) + ruido, 0, 255).astype(np.uint8))
    escritor.release()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--tipo", choices=["rojo", "comun", "negativo", "vacio"], default="comun")
    ap.add_argument("--salida", type=pathlib.Path, default=pathlib.Path("sintetico.mp4"))
    ap.add_argument("--todos", action="store_true", help="Genera los cuatro tipos y zonas.json")
    ap.add_argument("--carpeta", type=pathlib.Path, default=pathlib.Path("datos/sinteticos"))
    args = ap.parse_args()
    if args.todos:
        args.carpeta.mkdir(parents=True, exist_ok=True)
        for i, tipo in enumerate(["rojo", "comun", "negativo", "vacio"]):
            generar(tipo, args.carpeta / f"{tipo}_01.mp4", semilla=i)
        (args.carpeta / "zonas.json").write_text(json.dumps({"zonas": zonas()}, indent=2))
        print(f"✓ Videos y zonas.json en {args.carpeta}")
    else:
        generar(args.tipo, args.salida)
        print(f"✓ {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

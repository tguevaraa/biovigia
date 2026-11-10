#!/usr/bin/env python3
"""Mide la exactitud de asignación (RNF-08) y la tasa de eventos falsos (RNF-07).

Recorre los videos base de BVIA-32 sin servidor y compara lo que confirma la canalización
con lo que dice el nombre de cada archivo:

    rojo_*.mp4  → exactamente un evento en el rojo       (conforme)
    comun_*.mp4 → exactamente un evento en el común      (no conforme)
    negativo_*, vacio_* → ningún evento

    python herramientas/evaluar_reglas.py
    python herramientas/evaluar_reglas.py --detector movimiento --videos datos/sinteticos \\
        --zonas datos/sinteticos/zonas.json
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from vision.captura import FuenteArchivo  # noqa: E402
from vision.configuracion import desde_entorno  # noqa: E402
from vision.deteccion import ErrorModelo, crear_detector  # noqa: E402
from vision.pipeline import ServicioVision  # noqa: E402
from vision.zonas import ConjuntoZonas  # noqa: E402

ESPERADO = {"rojo": ["rojo"], "comun": ["comun"], "negativo": [], "vacio": []}
EXTENSIONES = {".mp4", ".mov", ".avi", ".mkv"}


def tipo_de(nombre: str) -> str | None:
    return next((t for t in ESPERADO if nombre.startswith(t)), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--videos", type=pathlib.Path, default=RAIZ / "datos" / "videos")
    ap.add_argument("--zonas", type=pathlib.Path, default=RAIZ / "vision" / "zonas.json")
    ap.add_argument("--detector", choices=["yolo", "movimiento"])
    ap.add_argument("--modelo", type=pathlib.Path)
    ap.add_argument("--mostrar", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    config = desde_entorno()
    if args.detector:
        config.detector = args.detector
    if args.modelo:
        config.modelo = args.modelo
    config.mostrar = args.mostrar
    zonas = ConjuntoZonas.cargar(args.zonas)
    if not zonas.completas:
        print(f"✗ {args.zonas} no tiene las dos zonas. Trázalas antes de evaluar.")
        return 1
    videos = sorted(p for p in args.videos.glob("*") if p.suffix.lower() in EXTENSIONES)
    if not videos:
        print(f"✗ No hay videos en {args.videos}")
        return 1

    positivos = aciertos = ventanas_sin_descarte = falsos = extra = 0
    print(f"{'video':<22}{'esperado':<12}{'obtenido':<22}resultado")
    print("-" * 66)
    for video in videos:
        tipo = tipo_de(video.stem)
        if tipo is None:
            continue
        try:
            detector = crear_detector(config.detector, config.modelo,
                                      config.parametros.umbral_confianza, config.imgsz)
        except ErrorModelo as exc:
            print(f"✗ {exc}")
            return 1
        fuente = FuenteArchivo(str(video), config.ancho, config.alto,
                               config.parametros.fps_muestreo)
        servicio = ServicioVision(config, fuente, detector, zonas)
        try:
            obtenido = [e.recipiente for e in servicio.ejecutar()]
        finally:
            fuente.cerrar()
        esperado = ESPERADO[tipo]
        if esperado:
            positivos += 1
            ok = obtenido[:1] == esperado
            aciertos += ok
            extra += max(0, len(obtenido) - 1)
        else:
            ventanas_sin_descarte += 1
            ok = not obtenido
            falsos += len(obtenido) > 0
        print(f"{video.name:<22}{(esperado or ['—'])[0]:<12}{', '.join(obtenido) or '—':<22}"
              f"{'✓' if ok and (not esperado or len(obtenido) == 1) else '✗'}")

    print("-" * 66)
    if positivos:
        exactitud = aciertos / positivos
        print(f"  RNF-08 exactitud de asignación: {aciertos}/{positivos} = {exactitud:.0%} "
              f"(meta ≥ 90 %){'  ✓' if exactitud >= 0.9 else '  ✗'}")
    denominador = ventanas_sin_descarte + positivos
    tasa = (falsos + extra) / denominador if denominador else 0.0
    print(f"  RNF-07 eventos falsos: {falsos} en {ventanas_sin_descarte} ventana(s) sin descarte"
          f" + {extra} duplicado(s) en descartes reales → {tasa:.0%} (meta ≤ 5 %)"
          f"{'  ✓' if tasa <= 0.05 else '  ✗'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

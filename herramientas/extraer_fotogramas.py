#!/usr/bin/env python3
"""BVIA-38 · Extrae imágenes de los videos base para anotarlas (1 de cada N fotogramas).

    python herramientas/extraer_fotogramas.py                     # datos/videos → datos/imagenes
    python herramientas/extraer_fotogramas.py --cada 10 --ancho 640

Las imágenes salen normalizadas a 640 × 480, igual que las ve el servicio de visión, con
nombres que conservan el video de origen (para partir 80/20 por video, no por imagen, y
evitar que fotogramas casi idénticos queden a la vez en entrenamiento y validación).
"""
from __future__ import annotations

import argparse
import pathlib
import sys

try:
    import cv2
except ImportError:
    sys.exit("Falta OpenCV: pip install -r requirements-vision.txt")

EXTENSIONES = {".mp4", ".mov", ".avi", ".mkv"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--videos", type=pathlib.Path, default=pathlib.Path("datos/videos"))
    ap.add_argument("--salida", type=pathlib.Path, default=pathlib.Path("datos/imagenes"))
    ap.add_argument("--cada", type=int, default=10, help="Guardar 1 de cada N fotogramas")
    ap.add_argument("--ancho", type=int, default=640)
    ap.add_argument("--alto", type=int, default=480)
    args = ap.parse_args()

    videos = sorted(p for p in args.videos.glob("*") if p.suffix.lower() in EXTENSIONES)
    if not videos:
        print(f"✗ No hay videos en {args.videos}")
        return 1
    args.salida.mkdir(parents=True, exist_ok=True)
    total = 0
    for video in videos:
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            print(f"  ✗ {video.name}: no se puede abrir")
            continue
        indice = guardadas = 0
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            if indice % args.cada == 0:
                cuadro = cv2.resize(cuadro, (args.ancho, args.alto), interpolation=cv2.INTER_AREA)
                destino = args.salida / f"{video.stem}_{indice:05d}.jpg"
                cv2.imwrite(str(destino), cuadro, [cv2.IMWRITE_JPEG_QUALITY, 92])
                guardadas += 1
            indice += 1
        cap.release()
        total += guardadas
        print(f"  {video.name:<22} {guardadas:>4} imágenes")
    print(f"✓ {total} imágenes en {args.salida}. Anótalas con las clases: gasa, "
          "recipiente_rojo, recipiente_comun (formato YOLO).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

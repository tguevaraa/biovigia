#!/usr/bin/env python3
"""Compara modelos por sus falsos positivos en fotos donde el objeto NO aparece.

    python herramientas/medir_falsos_positivos.py vision/modelos/biovigia-gasas-v0.1.pt \
        vision/modelos/biovigia-gasas-v0.2.pt
    python herramientas/medir_falsos_positivos.py --carpeta datos/externos/laboratorio/prueba/images m.pt

Usa la partición ``prueba`` que deja herramientas/grabar_negativos.py: fotos de la escena
real sin el objeto, que el entrenamiento nunca vio. Cualquier caja ahí es un falso
positivo. Informa, para varias confianzas, el % de fotogramas con al menos una caja falsa,
también aplicando el filtro de tamaño de la demostración (cajas de más del 2 % de la imagen
se descartan, como en probar_modelo.py).

Ojo: bajar los falsos positivos no sirve si el modelo deja de ver el objeto real. Mirar
también el mAP de validación que imprime entrenar_modelo.py.
"""
from __future__ import annotations

import argparse
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modelos", nargs="+", type=pathlib.Path)
    ap.add_argument("--carpeta", type=pathlib.Path,
                    default=RAIZ / "datos" / "externos" / "cuarto" / "prueba" / "images")
    ap.add_argument("--confianzas", type=float, nargs="+", default=[0.25, 0.35, 0.5])
    ap.add_argument("--area-max", type=float, default=0.02)
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    import cv2
    from ultralytics import YOLO

    fotos = sorted(args.carpeta.glob("*.jpg"))
    if not fotos:
        print(f"✗ No hay imágenes en {args.carpeta}")
        return 1
    imagenes = [cv2.imread(str(f)) for f in fotos]
    print(f"{len(fotos)} fotos sin el objeto · % con al menos un falso positivo\n")
    print(f"{'modelo':28s} {'confianza':>9s} {'todas':>8s} {'cajas':>6s} {'≤ área máx':>11s}")
    for ruta in args.modelos:
        m = YOLO(str(ruta))
        for conf in args.confianzas:
            con = cajas = con_chicas = 0
            for img in imagenes:
                area = img.shape[0] * img.shape[1]
                b = m.predict(img, conf=conf, imgsz=args.imgsz, verbose=False)[0].boxes.xyxy.tolist()
                chicas = [x for x in b if (x[2] - x[0]) * (x[3] - x[1]) <= args.area_max * area]
                con += bool(b)
                cajas += len(b)
                con_chicas += bool(chicas)
            n = len(imagenes)
            print(f"{ruta.stem:28s} {conf:9.2f} {100 * con / n:7.1f}% {cajas:6d} {100 * con_chicas / n:10.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

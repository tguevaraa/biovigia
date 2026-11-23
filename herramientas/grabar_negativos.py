#!/usr/bin/env python3
"""Graba fotogramas de una escena SIN el objeto, para usarlos como ejemplos negativos.

    python herramientas/grabar_negativos.py                               # 90 s, cámara 0
    python herramientas/grabar_negativos.py --segundos 120 --salida datos/externos/laboratorio
    python herramientas/grabar_negativos.py --video datos/videos/vacio_01.mp4 --cada 0.3

Para qué: un modelo entrenado con imágenes de internet confunde objetos de la escena real
con el objeto buscado (el modelo de gasas v0.1 marcaba como gasa un tacho blanco y un
teclado blanco). Si se le muestran fotos de ESA escena sin gasas, aprende qué no es una gasa.

Durante la grabación no debe verse el objeto (ninguna gasa). Las personas pueden moverse
con normalidad: conviene que aparezcan manos, ropa y objetos claros.

Los fotogramas se reparten por tiempo, no al azar, para que la prueba no tenga fotogramas
casi idénticos a los de entrenamiento: el primer 70 % a ``train``, el siguiente 15 % a
``val`` y el último 15 % a ``prueba`` (no se entrena con ella: es para medir con
herramientas/medir_falsos_positivos.py). Cada imagen lleva una etiqueta vacía (sin cajas).

Después se suma al dataset con:

    python herramientas/armar_dataset_tachos.py ... --negativas cuarto=datos/externos/cuarto
"""
from __future__ import annotations

import argparse
import pathlib
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fuente", type=int, default=0, help="Índice de cámara")
    ap.add_argument("--video", type=pathlib.Path, help="Tomar los fotogramas de un video en vez de la cámara")
    ap.add_argument("--segundos", type=float, default=90)
    ap.add_argument("--cada", type=float, default=0.5, help="Segundos entre fotogramas guardados")
    ap.add_argument("--salida", type=pathlib.Path, default=RAIZ / "datos" / "externos" / "cuarto")
    ap.add_argument("--prefijo", default="cuarto")
    args = ap.parse_args()

    import cv2

    if args.video:
        cap = cv2.VideoCapture(str(args.video))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
    else:
        cap = cv2.VideoCapture(args.fuente, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        for _ in range(30):          # la cámara del teléfono tarda en estabilizar la exposición
            cap.read()
    imagenes, negras, i = [], 0, 0
    inicio, ultimo = time.monotonic(), -1e9
    print(f"Grabando {'el video' if args.video else f'{args.segundos:.0f} s'}: que no se vea el objeto…")
    while True:
        ok, img = cap.read()
        if not ok:
            if args.video:
                break
            continue
        ahora = i / fps if args.video else time.monotonic() - inicio
        i += 1
        if not args.video and ahora > args.segundos:
            break
        if ahora - ultimo < args.cada:
            continue
        ultimo = ahora
        if img.mean() < 8:           # Iriun muestra negro mientras busca el teléfono
            negras += 1
            continue
        h, w = img.shape[:2]
        f = 1024 / max(h, w)         # mismo tamaño que las imágenes de Open Images y LVIS
        imagenes.append(cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA))
    cap.release()
    if not imagenes:
        print("✗ No se guardó ningún fotograma (¿la cámara está conectada?)")
        return 1

    n = len(imagenes)
    cortes = {"train": (0, int(n * 0.70)), "val": (int(n * 0.70), int(n * 0.85)), "prueba": (int(n * 0.85), n)}
    for particion, (a, b) in cortes.items():
        (args.salida / particion / "images").mkdir(parents=True, exist_ok=True)
        (args.salida / particion / "labels").mkdir(parents=True, exist_ok=True)
        for k in range(a, b):
            nombre = f"{args.prefijo}_{int(time.time())}_{k:04d}"
            cv2.imwrite(str(args.salida / particion / "images" / f"{nombre}.jpg"), imagenes[k],
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            (args.salida / particion / "labels" / f"{nombre}.txt").write_text("", encoding="utf-8")
    print(f"✓ {n} fotogramas ({negras} negros descartados) en {args.salida}: "
          + ", ".join(f"{p} {b - a}" for p, (a, b) in cortes.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

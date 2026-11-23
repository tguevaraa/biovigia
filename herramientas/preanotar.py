#!/usr/bin/env python3
"""Pre-anota los tachos de los clips propios con el modelo, para revisarlos en CVAT.

    python herramientas/preanotar.py                                  # datos/videos, modelo v0.2
    python herramientas/preanotar.py --videos datos/videos/luces --cada 5

En vez de dibujar cada caja, el modelo propone los tachos y una persona solo revisa:
corrige las cajas mal puestas, agrega las que faltan y borra las que sobran.

* Se recorre cada clip completo con el estabilizador (vision/estabilizador.py), así un
  tacho que el modelo no ve en un fotograma suelto conserva su caja.
* Se guarda 1 de cada N fotogramas, reducido a 640 × 480 sin deformar (igual que el
  servicio de visión).
* El tipo de cada tacho se decide por color: si el interior de la caja es mayormente
  rojo, ``recipiente_rojo``; si no, ``recipiente_comun``. Hay que revisarlo igual.

Salida en ``datos/anotaciones/preanotacion/``: por cada grupo de clips (rojo, comun,
negativo_vacio) un ``<grupo>_imagenes.zip`` para crear la tarea en CVAT y un
``<grupo>_yolo.zip`` para importar las cajas (formato «YOLO 1.1»), más ``muestra.jpg``.
Las etiquetas usan los nombres del proyecto BioVigIA de CVAT, en su mismo orden.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import zipfile
from collections import defaultdict

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

try:
    import cv2
    import numpy as np
    from ultralytics import YOLO

    from vision.captura import normalizar
    from vision.deteccion import fraccion_roja
    from vision.estabilizador import Estabilizador
    from vision.tipos import Deteccion
except ImportError:
    sys.exit("Faltan dependencias: pip install -r requirements-vision.txt")

ETIQUETAS = ["gasa", "recipiente_rojo", "recipiente_comun", "mano"]   # orden del proyecto CVAT
ROJO, COMUN = ETIQUETAS.index("recipiente_rojo"), ETIQUETAS.index("recipiente_comun")
ANCHO, ALTO = 640, 480
GRUPOS = {"rojo": ("rojo_",), "comun": ("comun_",), "negativo_vacio": ("negativo_", "vacio_")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", type=pathlib.Path, default=RAIZ / "datos" / "videos")
    ap.add_argument("--modelo", type=pathlib.Path,
                    default=RAIZ / "vision" / "modelos" / "biovigia-tachos-v0.2.pt")
    ap.add_argument("--salida", type=pathlib.Path,
                    default=RAIZ / "datos" / "anotaciones" / "preanotacion")
    ap.add_argument("--cada", type=int, default=10, help="Guardar 1 de cada N fotogramas")
    ap.add_argument("--confianza", type=float, default=0.30)
    ap.add_argument("--umbral-rojo", type=float, default=0.25,
                    help="Fracción roja mínima para llamar «rojo» a un tacho")
    args = ap.parse_args()

    videos = sorted(args.videos.glob("*.mp4"))
    if not videos or not args.modelo.exists():
        print(f"✗ Faltan videos en {args.videos} o el modelo {args.modelo}")
        return 1
    modelo = YOLO(str(args.modelo))
    args.salida.mkdir(parents=True, exist_ok=True)
    por_grupo: dict[str, list[tuple[str, np.ndarray, list[str]]]] = defaultdict(list)
    cuenta = defaultdict(int)
    muestras = []

    for video in videos:
        grupo = next((g for g, pref in GRUPOS.items() if video.name.startswith(pref)), "otros")
        estab = Estabilizador(umbral_alta=args.confianza, umbral_baja=0.15)
        cap = cv2.VideoCapture(str(video))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        indice = 0
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            imagen = normalizar(cuadro, ANCHO, ALTO)
            r = modelo.predict(imagen, conf=0.15, imgsz=640, verbose=False)[0]
            dets = [Deteccion("recipiente", c, *b)
                    for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist())]
            estables = estab.actualizar(dets, indice / fps)
            if indice % args.cada == 0:
                lineas = []
                for o in estables:
                    d = o.caja
                    clase = ROJO if fraccion_roja(imagen, d) >= args.umbral_rojo else COMUN
                    cx, cy = (d.x0 + d.x1) / 2 / ANCHO, (d.y0 + d.y1) / 2 / ALTO
                    lineas.append(f"{clase} {cx:.6f} {cy:.6f} {(d.x1 - d.x0) / ANCHO:.6f} "
                                  f"{(d.y1 - d.y0) / ALTO:.6f}")
                    cuenta[ETIQUETAS[clase]] += 1
                nombre = f"{video.stem}_{indice:05d}"
                por_grupo[grupo].append((nombre, imagen, lineas))
                cuenta["imagenes"] += 1
                cuenta[f"{len(lineas)} cajas"] += 1
                if indice == args.cada * 5 and len(muestras) < 20:
                    vista = imagen.copy()
                    for linea in lineas:
                        k, cx, cy, w, h = linea.split()
                        cx, cy, w, h = (float(cx) * ANCHO, float(cy) * ALTO,
                                        float(w) * ANCHO, float(h) * ALTO)
                        color = (0, 0, 255) if int(k) == ROJO else (200, 200, 200)
                        cv2.rectangle(vista, (int(cx - w / 2), int(cy - h / 2)),
                                      (int(cx + w / 2), int(cy + h / 2)), color, 3)
                    cv2.putText(vista, video.stem, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                                (0, 255, 255), 2)
                    muestras.append(cv2.resize(vista, (320, 240)))
            indice += 1
        cap.release()

    for grupo, filas in por_grupo.items():
        with zipfile.ZipFile(args.salida / f"{grupo}_imagenes.zip", "w") as zi, \
                zipfile.ZipFile(args.salida / f"{grupo}_yolo.zip", "w") as zy:
            zy.writestr("obj.names", "\n".join(ETIQUETAS) + "\n")
            zy.writestr("obj.data", f"classes = {len(ETIQUETAS)}\ntrain = data/train.txt\n"
                                    "names = data/obj.names\nbackup = backup/\n")
            zy.writestr("train.txt", "".join(f"data/obj_train_data/{n}.jpg\n" for n, _, _ in filas))
            for nombre, imagen, lineas in filas:
                ok, jpg = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 92])
                zi.writestr(f"{nombre}.jpg", jpg.tobytes())
                zy.writestr(f"obj_train_data/{nombre}.txt", "\n".join(lineas) + ("\n" if lineas else ""))
        print(f"  {grupo:<16} {len(filas):>4} imágenes → {grupo}_imagenes.zip + {grupo}_yolo.zip")

    if muestras:
        while len(muestras) % 5:
            muestras.append(np.zeros_like(muestras[0]))
        cv2.imwrite(str(args.salida / "muestra.jpg"),
                    np.vstack([np.hstack(muestras[i:i + 5]) for i in range(0, len(muestras), 5)]))
    resumen = ", ".join(f"{k}: {v}" for k, v in sorted(cuenta.items()))
    print(f"✓ {resumen}\n✓ Salida en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

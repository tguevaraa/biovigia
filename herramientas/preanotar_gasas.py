#!/usr/bin/env python3
"""Pre-anota las gasas de los clips propios combinando dos detectores, para CVAT.

    python herramientas/preanotar_gasas.py
    python herramientas/preanotar_gasas.py --sin-modelo          # solo movimiento

No hay datasets públicos de gasas, así que las propuestas salen de dos fuentes que se
complementan:

* **Movimiento** (``DetectorMovimiento``, el detector de desarrollo): objetos claros que se
  mueven sobre el fondo. Encuentra bien el papel o la gasa mientras cae, y no ve lo que
  ya está quieto dentro del tacho.
* **Modelo de gasas** (``biovigia-gasas-v0.1``, entrenado con sustitutos de LVIS): ayuda
  cuando la gasa está quieta en la mano. Se descartan sus cajas grandes, porque ese modelo
  tiende a encuadrar la mano entera.

Las cajas que se solapan se fusionan. Se guardan los mismos fotogramas y con los mismos
nombres que ``preanotar.py`` (1 de cada N, 640 × 480 sin deformar), así el zip se importa
en las tareas de CVAT que ya existen con el modo **Append**, sin borrar los tachos.

Salida: ``datos/anotaciones/preanotacion/<grupo>_gasas_yolo.zip`` y ``muestra_gasas.jpg``.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import zipfile
from collections import defaultdict

RAIZ = pathlib.Path(__file__).resolve().parents[1]
# La consola de Windows (cp1252) no tiene ✓, ▸ ni →: se reemplazan en vez de cortar.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(errors="replace")
sys.path.insert(0, str(RAIZ))

try:
    import cv2
    import numpy as np
    from ultralytics import YOLO

    from vision.captura import normalizar
    from vision.deteccion import DetectorMovimiento
    from vision.estabilizador import Estabilizador, iou
    from vision.tipos import GASA, MANO, Deteccion
except ImportError:
    sys.exit("Faltan dependencias: pip install -r requirements-vision.txt")

ETIQUETAS = ["gasa", "recipiente_rojo", "recipiente_comun", "mano"]   # orden del proyecto CVAT
ANCHO, ALTO = 640, 480
GRUPOS = {"rojo": ("rojo_",), "comun": ("comun_",), "negativo_vacio": ("negativo_", "vacio_")}
CALENTAMIENTO = 15          # fotogramas para que el detector de movimiento aprenda el fondo
AREA_MAX_MODELO = 0.03      # cajas del modelo más grandes que el 3 % de la imagen = la mano


def ampliar(d: Deteccion, factor: float) -> Deteccion:
    """La misma caja agrandada ``factor`` veces su ancho y alto hacia cada lado."""
    dx, dy = (d.x1 - d.x0) * factor, (d.y1 - d.y0) * factor
    return Deteccion(d.clase, d.confianza, d.x0 - dx, d.y0 - dy, d.x1 + dx, d.y1 + dy)


def contiene_centro(zona: Deteccion, d: Deteccion) -> bool:
    cx, cy = (d.x0 + d.x1) / 2, (d.y0 + d.y1) / 2
    return zona.x0 <= cx <= zona.x1 and zona.y0 <= cy <= zona.y1


def forma_de_objeto(d: Deteccion) -> bool:
    """Descarta franjas finas (bordes de sombras y reflejos) y manchas enormes."""
    w, h = d.x1 - d.x0, d.y1 - d.y0
    if w <= 0 or h <= 0:
        return False
    return 1 / 3 <= w / h <= 3 and w * h <= 0.02 * ANCHO * ALTO


def fusionar(dets: list[Deteccion], umbral: float = 0.3) -> list[Deteccion]:
    """Quita duplicados: de cada grupo solapado queda la de mayor confianza."""
    quedan: list[Deteccion] = []
    for d in sorted(dets, key=lambda d: d.confianza, reverse=True):
        if all(iou(d, q) < umbral for q in quedan):
            quedan.append(d)
    return quedan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", type=pathlib.Path, default=RAIZ / "datos" / "videos")
    ap.add_argument("--modelo", type=pathlib.Path,
                    default=RAIZ / "vision" / "modelos" / "biovigia-gasas-v0.1.pt")
    ap.add_argument("--sin-modelo", action="store_true", help="Solo el detector de movimiento")
    ap.add_argument("--modelo-tachos", type=pathlib.Path,
                    default=RAIZ / "vision" / "modelos" / "biovigia-tachos-v0.2.pt",
                    help="Para quedarse solo con lo que pasa cerca de los recipientes")
    ap.add_argument("--salida", type=pathlib.Path,
                    default=RAIZ / "datos" / "anotaciones" / "preanotacion")
    ap.add_argument("--cada", type=int, default=10, help="Igual que en preanotar.py")
    ap.add_argument("--confianza", type=float, default=0.35)
    args = ap.parse_args()

    videos = sorted(args.videos.glob("*.mp4"))
    if not videos:
        print(f"✗ No hay videos en {args.videos}")
        return 1
    modelo = None if args.sin_modelo or not args.modelo.exists() else YOLO(str(args.modelo))
    tachos = YOLO(str(args.modelo_tachos))
    args.salida.mkdir(parents=True, exist_ok=True)
    por_grupo: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    cuenta = defaultdict(int)
    muestras: list[tuple[float, np.ndarray]] = []

    for video in videos:
        grupo = next((g for g, pref in GRUPOS.items() if video.name.startswith(pref)), "otros")
        movimiento = DetectorMovimiento(detectar_mano=True)
        estab = Estabilizador(umbral_alta=0.3, umbral_baja=0.15, retener_s=5.0)
        cap = cv2.VideoCapture(str(video))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        indice, mejor = 0, None
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            imagen = normalizar(cuadro, ANCHO, ALTO)
            # El detector de movimiento necesita ver todos los fotogramas para aprender el fondo.
            vistas = movimiento.detectar(imagen)
            if indice % args.cada != 0:
                indice += 1
                continue
            r = tachos.predict(imagen, conf=0.15, imgsz=640, verbose=False)[0]
            recipientes = [o.caja for o in estab.actualizar(
                [Deteccion("recipiente", c, *b) for b, c in
                 zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist())], indice / fps)]
            manos = [ampliar(d, 0.5) for d in vistas if d.clase == MANO]
            propuestas = [d for d in vistas if d.clase == GASA] if indice >= CALENTAMIENTO else []
            if modelo is not None:
                r = modelo.predict(imagen, conf=args.confianza, imgsz=640, verbose=False)[0]
                for (x0, y0, x1, y1), c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist()):
                    if (x1 - x0) * (y1 - y0) <= AREA_MAX_MODELO * ANCHO * ALTO:
                        propuestas.append(Deteccion(GASA, c, x0, y0, x1, y1))
            # Una gasa que importa está cerca de un recipiente y, además, en una mano o
            # dentro de la boca del recipiente (cayendo). Lo demás es reflejo o sombra.
            cerca = [ampliar(t, 0.6) for t in recipientes]
            cajas = fusionar([
                d for d in propuestas
                if forma_de_objeto(d)
                and any(contiene_centro(z, d) for z in cerca)
                and (any(contiene_centro(m, d) for m in manos)
                     or any(contiene_centro(t, d) for t in recipientes))])
            lineas = [f"0 {(d.x0 + d.x1) / 2 / ANCHO:.6f} {(d.y0 + d.y1) / 2 / ALTO:.6f} "
                      f"{(d.x1 - d.x0) / ANCHO:.6f} {(d.y1 - d.y0) / ALTO:.6f}" for d in cajas]
            por_grupo[grupo].append((f"{video.stem}_{indice:05d}", lineas))
            cuenta["imagenes"] += 1
            cuenta["con gasa"] += bool(lineas)
            cuenta["cajas"] += len(lineas)
            if cajas and (mejor is None or len(cajas) > mejor[0]):
                vista = imagen.copy()
                for d in cajas:
                    cv2.rectangle(vista, (int(d.x0), int(d.y0)), (int(d.x1), int(d.y1)),
                                  (255, 255, 0), 2)
                cv2.putText(vista, video.stem, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                            (0, 255, 255), 2)
                mejor = (len(cajas), vista)
            indice += 1
        cap.release()
        if mejor is not None:
            muestras.append((0, cv2.resize(mejor[1], (320, 240))))

    for grupo, filas in por_grupo.items():
        with zipfile.ZipFile(args.salida / f"{grupo}_gasas_yolo.zip", "w") as zy:
            zy.writestr("obj.names", "\n".join(ETIQUETAS) + "\n")
            zy.writestr("obj.data", f"classes = {len(ETIQUETAS)}\ntrain = data/train.txt\n"
                                    "names = data/obj.names\nbackup = backup/\n")
            zy.writestr("train.txt", "".join(f"data/obj_train_data/{n}.jpg\n" for n, _ in filas))
            for nombre, lineas in filas:
                zy.writestr(f"obj_train_data/{nombre}.txt", "\n".join(lineas) + ("\n" if lineas else ""))
        con = sum(1 for _, l in filas if l)
        print(f"  {grupo:<16} {len(filas):>4} imágenes, {con:>3} con gasa → {grupo}_gasas_yolo.zip")

    if muestras:
        vistas = [v for _, v in muestras][:20]
        while len(vistas) % 5:
            vistas.append(np.zeros_like(vistas[0]))
        cv2.imwrite(str(args.salida / "muestra_gasas.jpg"),
                    np.vstack([np.hstack(vistas[i:i + 5]) for i in range(0, len(vistas), 5)]))
    print(f"✓ {dict(cuenta)} · salida en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

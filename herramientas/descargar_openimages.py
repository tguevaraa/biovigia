#!/usr/bin/env python3
"""Descarga de Open Images V7 las clases útiles para BioVigIA, ya en formato YOLO.

    python herramientas/descargar_openimages.py                      # tachos + personas
    python herramientas/descargar_openimages.py --max-personas 1000 --hilos 16

Open Images (Google) publica imágenes con licencia CC BY 2.0 y cajas anotadas con licencia
CC BY 4.0. Hay que citarlo en el informe: Kuznetsova et al., «The Open Images Dataset V4»,
IJCV 2020. Se bajan solo:

* ``Waste container`` → clase 0 ``recipiente`` (todas las imágenes que tengan uno);
* ``Person``          → clase 1 ``persona`` (las que salen junto a un tacho, más una
  muestra de imágenes solo con personas, para que el modelo no vea tachos en todas partes).

Las anotaciones de entrenamiento pesan 2,26 GB: se leen mientras se descargan y se guarda
solo lo filtrado (``anotaciones.csv``), así una segunda ejecución no vuelve a bajarlas.
Las imágenes se reducen a 1024 px de lado mayor para ahorrar disco (las cajas YOLO son
relativas, no cambian). Resultado en ``datos/externos/openimages/``, fuera del repositorio.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import cv2
    import numpy as np
    import requests
except ImportError:
    sys.exit("Faltan dependencias: pip install -r requirements-vision.txt")

RAIZ = pathlib.Path(__file__).resolve().parents[1]
ANOTACIONES = {
    "train": "https://storage.googleapis.com/openimages/v6/oidv6-train-annotations-bbox.csv",
    "validation": "https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv",
}
IMAGEN = "https://open-images-dataset.s3.amazonaws.com/{split}/{id}.jpg"
CLASES = {"/m/0bjyj5": 0, "/m/01g317": 1}   # Waste container, Person
NOMBRES = ["recipiente", "persona"]
RECIPIENTE, PERSONA = 0, 1
LADO_MAX = 1024


def filtrar(split: str, cache: pathlib.Path) -> list[dict]:
    """Filas de las dos clases, sin dibujos (IsDepiction). Usa la caché si existe."""
    if cache.exists():
        with cache.open(encoding="utf-8") as f:
            return list(csv.DictReader(f))
    print(f"  Leyendo anotaciones de {split} (se filtran mientras bajan)…", flush=True)
    filas = []
    with requests.get(ANOTACIONES[split], stream=True, timeout=60) as r:
        r.raise_for_status()
        lineas = (b.decode("utf-8") for b in r.iter_lines(chunk_size=1 << 20) if b)
        for i, fila in enumerate(csv.DictReader(lineas)):
            if fila["LabelName"] in CLASES and fila["IsDepiction"] != "1":
                filas.append(fila)
            if i and i % 2_000_000 == 0:
                print(f"    {i / 1e6:.0f} M filas leídas, {len(filas)} útiles", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    return filas


def elegir(filas: list[dict], max_personas: int, semilla: int) -> dict[str, list[dict]]:
    """Todas las imágenes con tacho y una muestra de las que solo tienen personas."""
    por_imagen: dict[str, list[dict]] = defaultdict(list)
    for fila in filas:
        por_imagen[fila["ImageID"]].append(fila)
    con_tacho = [i for i, fs in por_imagen.items()
                 if any(CLASES[f["LabelName"]] == RECIPIENTE for f in fs)]
    solo_personas = sorted(set(por_imagen) - set(con_tacho))
    random.Random(semilla).shuffle(solo_personas)
    elegidas = con_tacho + solo_personas[:max_personas]
    return {i: por_imagen[i] for i in elegidas}


def bajar(sesion: requests.Session, split: str, imagen_id: str, filas: list[dict],
          carpeta: pathlib.Path) -> bool:
    destino = carpeta / "images" / f"{imagen_id}.jpg"
    etiqueta = carpeta / "labels" / f"{imagen_id}.txt"
    if destino.exists() and etiqueta.exists():
        return True
    try:
        r = sesion.get(IMAGEN.format(split=split, id=imagen_id), timeout=30)
        r.raise_for_status()
        imagen = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    except (requests.RequestException, cv2.error):
        return False
    if imagen is None:
        return False
    alto, ancho = imagen.shape[:2]
    escala = LADO_MAX / max(alto, ancho)
    if escala < 1:
        imagen = cv2.resize(imagen, (round(ancho * escala), round(alto * escala)),
                            interpolation=cv2.INTER_AREA)
    lineas = []
    for f in filas:
        x0, x1, y0, y1 = (float(f[k]) for k in ("XMin", "XMax", "YMin", "YMax"))
        if x1 <= x0 or y1 <= y0:
            continue
        lineas.append(f"{CLASES[f['LabelName']]} {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} "
                      f"{x1 - x0:.6f} {y1 - y0:.6f}")
    cv2.imwrite(str(destino), imagen, [cv2.IMWRITE_JPEG_QUALITY, 90])
    etiqueta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=pathlib.Path,
                    default=RAIZ / "datos" / "externos" / "openimages")
    ap.add_argument("--max-personas", type=int, default=2000,
                    help="Imágenes de entrenamiento solo con personas (sin tacho)")
    ap.add_argument("--hilos", type=int, default=16)
    ap.add_argument("--semilla", type=int, default=7)
    args = ap.parse_args()

    sesion = requests.Session()
    sesion.headers["User-Agent"] = "biovigia-dataset/1.0"
    for split, nombre in (("validation", "val"), ("train", "train")):
        print(f"▸ {split}")
        filas = filtrar(split, args.salida / "crudo" / f"{split}-anotaciones.csv")
        maximo = args.max_personas if split == "train" else args.max_personas // 5
        elegidas = elegir(filas, maximo, args.semilla)
        carpeta = args.salida / nombre
        (carpeta / "images").mkdir(parents=True, exist_ok=True)
        (carpeta / "labels").mkdir(parents=True, exist_ok=True)
        tachos = sum(1 for fs in elegidas.values()
                     if any(CLASES[f["LabelName"]] == RECIPIENTE for f in fs))
        print(f"  {len(elegidas)} imágenes ({tachos} con tacho). Descargando…", flush=True)
        bien = mal = 0
        with ThreadPoolExecutor(args.hilos) as pool:
            tareas = [pool.submit(bajar, sesion, split, i, fs, carpeta)
                      for i, fs in elegidas.items()]
            for n, t in enumerate(as_completed(tareas), 1):
                bien, mal = (bien + 1, mal) if t.result() else (bien, mal + 1)
                if n % 500 == 0:
                    print(f"    {n}/{len(tareas)}", flush=True)
        print(f"  ✓ {bien} descargadas, {mal} fallidas")

    yaml = args.salida / "dataset.yaml"
    yaml.write_text(
        "# Open Images V7 · tachos y personas (herramientas/descargar_openimages.py)\n"
        f"path: {args.salida.resolve().as_posix()}\n"
        "train: train/images\nval: val/images\nnames:\n"
        + "".join(f"  {i}: {n}\n" for i, n in enumerate(NOMBRES)), encoding="utf-8")
    print(f"✓ Dataset listo: {yaml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

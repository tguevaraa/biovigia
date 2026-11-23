#!/usr/bin/env python3
"""Descarga de LVIS v1 los tachos y baldes (escenas de interior), ya en formato YOLO.

    python herramientas/descargar_lvis.py
    python herramientas/descargar_lvis.py --sin-baldes
    python herramientas/descargar_lvis.py --categorias bandage tissue_paper paper_towel \
        --salida datos/externos/lvis-gasas          # sustitutos de la gasa (no hay «gauze»)

LVIS (Gupta et al., CVPR 2019) anota objetos sobre las fotos de COCO 2017, casi todas de
interiores cotidianos (cocinas, oficinas, baños). Anotaciones CC BY 4.0; imágenes de Flickr
con licencias Creative Commons (ver el campo ``license`` de cada imagen). Hay que citar
LVIS y COCO en el informe.

Se toman las categorías ``trash_can`` (garbage_can, wastebin, dustbin) y ``bucket``
(pail) como clase 0 ``recipiente``. Se descartan las imágenes donde LVIS marca la
categoría como no exhaustiva (podría haber tachos sin caja). Resultado en
``datos/externos/lvis/``, fuera del repositorio.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import cv2
    import numpy as np
    import requests
except ImportError:
    sys.exit("Faltan dependencias: pip install -r requirements-vision.txt")

RAIZ = pathlib.Path(__file__).resolve().parents[1]
# La consola de Windows (cp1252) no tiene ✓, ▸ ni →: se reemplazan en vez de cortar.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(errors="replace")
ANOTACIONES = "https://dl.fbaipublicfiles.com/LVIS/lvis_v1_{split}.json.zip"
LADO_MAX = 1024


def anotaciones(split: str, crudo: pathlib.Path) -> dict:
    zip_ = crudo / f"lvis_v1_{split}.json.zip"
    if not zip_.exists():
        print(f"  Descargando anotaciones de {split}…", flush=True)
        crudo.mkdir(parents=True, exist_ok=True)
        with requests.get(ANOTACIONES.format(split=split), stream=True, timeout=60) as r:
            r.raise_for_status()
            with zip_.open("wb") as f:
                for trozo in r.iter_content(1 << 20):
                    f.write(trozo)
    with zipfile.ZipFile(zip_) as z:
        return json.load(z.open(f"lvis_v1_{split}.json"))


def bajar(sesion: requests.Session, imagen: dict, cajas: list[list[float]],
          carpeta: pathlib.Path) -> bool:
    nombre = pathlib.Path(imagen["coco_url"]).stem
    destino = carpeta / "images" / f"{nombre}.jpg"
    etiqueta = carpeta / "labels" / f"{nombre}.txt"
    if destino.exists() and etiqueta.exists():
        return True
    try:
        r = sesion.get(imagen["coco_url"], timeout=30)
        r.raise_for_status()
        datos = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    except (requests.RequestException, cv2.error):
        return False
    if datos is None:
        return False
    alto, ancho = imagen["height"], imagen["width"]
    escala = LADO_MAX / max(alto, ancho)
    if escala < 1:
        datos = cv2.resize(datos, (round(datos.shape[1] * escala), round(datos.shape[0] * escala)),
                           interpolation=cv2.INTER_AREA)
    lineas = [f"0 {(x + w / 2) / ancho:.6f} {(y + h / 2) / alto:.6f} {w / ancho:.6f} {h / alto:.6f}"
              for x, y, w, h in cajas if w > 1 and h > 1]
    cv2.imwrite(str(destino), datos, [cv2.IMWRITE_JPEG_QUALITY, 90])
    etiqueta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=pathlib.Path, default=RAIZ / "datos" / "externos" / "lvis")
    ap.add_argument("--crudo", type=pathlib.Path,
                    default=RAIZ / "datos" / "externos" / "lvis" / "crudo",
                    help="Dónde guardar (o reusar) los zips de anotaciones de LVIS")
    ap.add_argument("--sin-baldes", action="store_true", help="Solo trash_can, sin bucket")
    ap.add_argument("--categorias", nargs="+",
                    help="Categorías de LVIS a bajar como clase 0, en vez de tachos y baldes "
                         "(p. ej. bandage tissue_paper paper_towel para las gasas)")
    ap.add_argument("--hilos", type=int, default=16)
    args = ap.parse_args()
    if args.categorias:
        nombres = set(args.categorias)
    else:
        nombres = {"trash_can"} if args.sin_baldes else {"trash_can", "bucket"}

    sesion = requests.Session()
    sesion.headers["User-Agent"] = "biovigia-dataset/1.0"
    for split, carpeta_nombre in (("val", "val"), ("train", "train")):
        print(f"▸ {split}")
        d = anotaciones(split, args.crudo)
        ids = {c["id"] for c in d["categories"] if c["name"] in nombres}
        cajas: dict[int, list] = defaultdict(list)
        for a in d["annotations"]:
            if a["category_id"] in ids:
                cajas[a["image_id"]].append(a["bbox"])
        imagenes = {i["id"]: i for i in d["images"]}
        elegidas = [(imagenes[i], cs) for i, cs in cajas.items()
                    if not ids & set(imagenes[i].get("not_exhaustive_category_ids", []))]
        print(f"  {len(elegidas)} imágenes ({sum(len(c) for _, c in elegidas)} cajas). "
              "Descargando…", flush=True)
        carpeta = args.salida / carpeta_nombre
        (carpeta / "images").mkdir(parents=True, exist_ok=True)
        (carpeta / "labels").mkdir(parents=True, exist_ok=True)
        bien = mal = 0
        with ThreadPoolExecutor(args.hilos) as pool:
            for t in as_completed([pool.submit(bajar, sesion, im, cs, carpeta)
                                   for im, cs in elegidas]):
                bien, mal = (bien + 1, mal) if t.result() else (bien, mal + 1)
        print(f"  ✓ {bien} descargadas, {mal} fallidas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

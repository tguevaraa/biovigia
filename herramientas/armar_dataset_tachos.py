#!/usr/bin/env python3
"""Junta Open Images y LVIS en un dataset de una sola clase: ``recipiente``.

    python herramientas/descargar_openimages.py     # contenedores de calle (y personas)
    python herramientas/descargar_lvis.py           # tachos y baldes de interior
    python herramientas/armar_dataset_tachos.py     # → datos/externos/tachos/dataset.yaml

    # Gasas: sustitutos de LVIS + fotos de Open Images como negativas
    python herramientas/armar_dataset_tachos.py --clase gasa --salida datos/externos/gasas \
        --fuente lvisg=datos/externos/lvis-gasas \
        --negativas oi=datos/externos/openimages --max-negativas 800

Las personas se quitan: LVIS no las anota en todas las imágenes donde aparecen, y mezclar
anotaciones incompletas enseña al modelo que «a veces una persona no es persona». Para
las personas se usa el YOLO original (COCO). Las imágenes de Open Images que solo tenían
personas quedan como ejemplos negativos (sin cajas): enseñan dónde NO hay un tacho.

Las imágenes se enlazan (hard link) en vez de copiarse, así no se duplica el disco.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil

RAIZ = pathlib.Path(__file__).resolve().parents[1]
EXTERNOS = RAIZ / "datos" / "externos"
FUENTES = {"oi": EXTERNOS / "openimages", "lvis": EXTERNOS / "lvis"}


def enlazar(origen: pathlib.Path, destino: pathlib.Path) -> None:
    if destino.exists():
        return
    try:
        os.link(origen, destino)
    except OSError:
        shutil.copy2(origen, destino)


def pares(valores: list[str] | None, defecto: dict[str, pathlib.Path]) -> dict[str, pathlib.Path]:
    """«prefijo=ruta» → {prefijo: ruta}; rutas relativas a la raíz del repositorio."""
    if not valores:
        return dict(defecto)
    salida = {}
    for v in valores:
        prefijo, _, ruta = v.partition("=")
        salida[prefijo] = (RAIZ / ruta) if not pathlib.Path(ruta).is_absolute() else pathlib.Path(ruta)
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=pathlib.Path, default=EXTERNOS / "tachos")
    ap.add_argument("--clase", default="recipiente", help="Nombre de la clase 0")
    ap.add_argument("--fuente", action="append",
                    help="prefijo=carpeta con train/ y val/ en YOLO (se usa su clase 0). "
                         "Por defecto: Open Images y LVIS (tachos)")
    ap.add_argument("--negativas", action="append", default=[],
                    help="prefijo=carpeta cuyas imágenes entran SIN cajas (ejemplos negativos)")
    ap.add_argument("--max-negativas", type=int, default=0,
                    help="Máximo de imágenes negativas por fuente y partición (0 = todas)")
    args = ap.parse_args()
    fuentes = [(p, c, False) for p, c in pares(args.fuente, FUENTES).items()]
    fuentes += [(p, c, True) for p, c in pares(args.negativas, {}).items()]

    for particion in ("train", "val"):
        imagenes = args.salida / particion / "images"
        etiquetas = args.salida / particion / "labels"
        imagenes.mkdir(parents=True, exist_ok=True)
        etiquetas.mkdir(parents=True, exist_ok=True)
        resumen = []
        for prefijo, carpeta, solo_negativas in fuentes:
            origen = carpeta / particion
            if not origen.exists():
                print(f"  ✗ Falta {origen}: corre antes el script de descarga")
                return 1
            con_tacho = negativas = cajas = 0
            for etiqueta in sorted((origen / "labels").glob("*.txt")):
                imagen = origen / "images" / f"{etiqueta.stem}.jpg"
                if not imagen.exists():
                    continue
                if solo_negativas and args.max_negativas and negativas >= args.max_negativas:
                    break
                lineas = [] if solo_negativas else [
                    l for l in etiqueta.read_text(encoding="utf-8").splitlines() if l.startswith("0 ")]
                nombre = f"{prefijo}_{etiqueta.stem}"
                enlazar(imagen, imagenes / f"{nombre}.jpg")
                (etiquetas / f"{nombre}.txt").write_text(
                    "\n".join(lineas) + ("\n" if lineas else ""), encoding="utf-8")
                if lineas:
                    con_tacho += 1
                    cajas += len(lineas)
                else:
                    negativas += 1
            resumen.append(f"{prefijo}: {con_tacho} con {args.clase} ({cajas} cajas), "
                           f"{negativas} negativas")
        print(f"▸ {particion}: " + " · ".join(resumen))

    yaml = args.salida / "dataset.yaml"
    yaml.write_text(
        f"# Una clase ({args.clase}) · {', '.join(p for p, _, _ in fuentes)} "
        "(herramientas/armar_dataset_tachos.py)\n"
        f"path: {args.salida.resolve().as_posix()}\n"
        f"train: train/images\nval: val/images\nnames:\n  0: {args.clase}\n", encoding="utf-8")
    print(f"✓ {yaml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

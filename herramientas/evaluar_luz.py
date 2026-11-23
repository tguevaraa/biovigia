#!/usr/bin/env python3
"""Mide cuánto le afecta la iluminación a un modelo de tachos, con los videos propios.

    python herramientas/evaluar_luz.py                                    # tachos: v0.2 vs v0.3
    python herramientas/evaluar_luz.py --objeto gasas                     # gasas: v0.1 (y v0.2)
    python herramientas/evaluar_luz.py --modelos vision/modelos/a.pt vision/modelos/b.pt

Toma fotogramas de ``datos/videos`` (siempre hay 2 tachos a la vista) y les aplica cambios
de luz simulados: oscuro, sobreexpuesto, lámpara cálida, bajo contraste. Para cada modelo
informa el porcentaje de fotogramas en que encuentra los 2 tachos. No sustituye a grabar
con luces reales distintas, pero permite comparar modelos con la misma prueba.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

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
except ImportError:
    sys.exit("Faltan dependencias: pip install -r requirements-vision.txt")

# nombre: (gamma, ganancia, tinte BGR o None)
ESCENAS = {
    "normal": (1.0, 1.0, None),
    "oscuro (luz apagada)": (1.8, 0.45, None),
    "muy oscuro": (2.4, 0.3, None),
    "sobreexpuesto (sol)": (0.55, 1.35, None),
    "muy sobreexpuesto": (0.45, 1.6, None),
    "luz cálida (lámpara)": (1.2, 0.8, (0.7, 0.9, 1.2)),
    "luz fría (fluorescente)": (0.9, 1.1, (1.2, 1.0, 0.8)),
    "contraste bajo": (0.8, 0.6, None),
}


def iluminar(imagen: np.ndarray, gamma: float, ganancia: float, tinte) -> np.ndarray:
    x = (imagen.astype(np.float32) / 255.0) ** gamma * ganancia
    if tinte is not None:
        x = x * np.array(tinte, np.float32)
    return np.clip(x * 255, 0, 255).astype(np.uint8)


def fotogramas(carpeta: pathlib.Path, cada: int,
               excluir: tuple[str, ...] = ()) -> list[np.ndarray]:
    """1 de cada N fotogramas, reducidos a 1280 px de ancho (el modelo usa 640 igual y así
    caben en memoria: a 1920 × 1080 la medición de gasas ocupaba casi 4 GB)."""
    salida = []
    for video in sorted(carpeta.glob("*.mp4")):
        if video.name.startswith(excluir):
            continue
        cap = cv2.VideoCapture(str(video))
        i = 0
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            if i % cada == 0:
                if cuadro.shape[1] > 1280:
                    escala = 1280 / cuadro.shape[1]
                    cuadro = cv2.resize(cuadro, None, fx=escala, fy=escala,
                                        interpolation=cv2.INTER_AREA)
                salida.append(cuadro)
            i += 1
        cap.release()
    return salida


# Qué cuenta como acierto en cada objeto. Tachos: siempre hay 2 a la vista. Gasas: aparecen
# solo un rato (en la mano, cayendo), así que se mide el % de fotogramas con alguna, sin
# los clips «vacio_», y se compara contra la luz normal.
OBJETOS = {
    "tachos": dict(modelos=("biovigia-tachos-v0.2.pt", "biovigia-tachos-v0.3.pt"),
                   cada=60, confianza=0.35, excluir=()),
    "gasas": dict(modelos=("biovigia-gasas-v0.1.pt", "biovigia-gasas-v0.2.pt"),
                  cada=10, confianza=0.30, excluir=("vacio_",)),
}


def main() -> int:
    modelos = RAIZ / "vision" / "modelos"
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--objeto", choices=list(OBJETOS), default="tachos")
    ap.add_argument("--modelos", type=pathlib.Path, nargs="+",
                    help="Por defecto, las versiones conocidas del objeto elegido")
    ap.add_argument("--videos", type=pathlib.Path, default=RAIZ / "datos" / "videos")
    ap.add_argument("--cada", type=int, help="1 de cada N fotogramas")
    ap.add_argument("--confianza", type=float)
    ap.add_argument("--tachos", type=int, default=2, help="Tachos visibles en la escena")
    args = ap.parse_args()
    perfil = OBJETOS[args.objeto]
    rutas = args.modelos or [modelos / m for m in perfil["modelos"]]
    cada = args.cada or perfil["cada"]
    confianza = args.confianza if args.confianza is not None else perfil["confianza"]
    minimo = args.tachos if args.objeto == "tachos" else 1

    cuadros = fotogramas(args.videos, cada, perfil["excluir"])
    if not cuadros:
        print(f"✗ No hay videos en {args.videos}")
        return 1
    cargados = [(p.stem, YOLO(str(p))) for p in rutas if p.exists()]
    if not cargados:
        print("✗ No existe ninguno de los modelos indicados")
        return 1
    que = f"con los {minimo} tachos" if args.objeto == "tachos" else "con alguna gasa"
    print(f"{len(cuadros)} fotogramas · % {que} (confianza ≥ {confianza})\n", flush=True)
    print(f"{'Luz':<26}" + "".join(f"{n:>26}" for n, _ in cargados), flush=True)
    for escena, (gamma, ganancia, tinte) in ESCENAS.items():
        celdas = []
        for _, modelo in cargados:
            vistos = [len(modelo.predict(iluminar(c, gamma, ganancia, tinte), conf=confianza,
                                         imgsz=640, verbose=False)[0].boxes) for c in cuadros]
            celdas.append(f"{100 * sum(v >= minimo for v in vistos) / len(vistos):.1f} %")
        print(f"{escena:<26}" + "".join(f"{c:>26}" for c in celdas), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""BVIA-39/40 · Entrena el detector por transferencia de aprendizaje y verifica OE2.

    python herramientas/entrenar_modelo.py                          # yolo11n, 100 épocas
    python herramientas/entrenar_modelo.py --base yolov8n.pt --epocas 60
    python herramientas/entrenar_modelo.py --solo-evaluar vision/modelos/biovigia-gasa-v0.1.pt

Al terminar copia los mejores pesos a vision/modelos/<nombre>.pt e informa los criterios del
OE2 y del RNF-11: mAP@0,5 ≥ 0,80, ≤ 3 M de parámetros y ≤ 5 GFLOPs. La medición de los
15 fps (RNF-09) se hace en el equipo de despliegue con --medir-fps.

Nota: yolo11n tiene ~2,6 M de parámetros (cumple RNF-11) pero ~6,5 GFLOPs a 640 px; para
bajar de 5 GFLOPs se entrena e infiere con --imgsz 512. yolov8n tiene ~3,2 M (no cumple).
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def resumen(modelo, imgsz: int) -> tuple[float, float]:
    parametros = sum(p.numel() for p in modelo.model.parameters())
    try:
        from ultralytics.utils.torch_utils import get_flops

        gflops = float(get_flops(modelo.model, imgsz))
    except Exception:  # noqa: BLE001 - la API cambia entre versiones
        gflops = float("nan")
    return parametros / 1e6, gflops


def medir_fps(modelo, imgsz: int, repeticiones: int = 30, muestras: int = 100) -> float:
    """RNF-09: promedio de 30 repeticiones sobre 100 muestras de 640 × 480."""
    import numpy as np

    imagenes = [np.random.randint(0, 255, (480, 640, 3), np.uint8) for _ in range(muestras)]
    modelo.predict(imagenes[0], imgsz=imgsz, verbose=False)  # calentamiento
    tiempos = []
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        for img in imagenes:
            modelo.predict(img, imgsz=imgsz, verbose=False)
        tiempos.append(muestras / (time.perf_counter() - inicio))
    return sum(tiempos) / len(tiempos)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--datos", type=pathlib.Path, default=RAIZ / "datos" / "dataset.yaml")
    ap.add_argument("--base", default="yolo11n.pt", help="Pesos preentrenados de partida")
    ap.add_argument("--epocas", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--lote", type=int, default=16)
    ap.add_argument("--nombre", default="biovigia-gasa-v0.1")
    ap.add_argument("--dispositivo", default=None, help="cpu, 0 (GPU), mps…")
    ap.add_argument("--solo-evaluar", type=pathlib.Path, help="Evalúa unos pesos ya entrenados")
    ap.add_argument("--medir-fps", action="store_true", help="Mide fps en este equipo (RNF-09)")
    args = ap.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        print("✗ Falta ultralytics: pip install -r requirements-vision.txt")
        return 1
    if not args.datos.exists():
        print(f"✗ No existe {args.datos}. Copia datos/dataset.ejemplo.yaml y ajusta las rutas.")
        return 1

    if args.solo_evaluar:
        pesos = args.solo_evaluar
    else:
        modelo = YOLO(args.base)
        modelo.train(data=str(args.datos), epochs=args.epocas, imgsz=args.imgsz,
                     batch=args.lote, device=args.dispositivo, project=str(RAIZ / "datos" / "runs"),
                     name=args.nombre, exist_ok=True,
                     # Aumentaciones moderadas: la escena es fija y la cámara no rota.
                     degrees=0.0, flipud=0.0, fliplr=0.5, mosaic=1.0, hsv_v=0.4, scale=0.3)
        mejores = RAIZ / "datos" / "runs" / args.nombre / "weights" / "best.pt"
        destino = RAIZ / "vision" / "modelos" / f"{args.nombre}.pt"
        shutil.copy2(mejores, destino)
        print(f"✓ Pesos copiados a {destino.relative_to(RAIZ)}")
        pesos = destino

    modelo = YOLO(str(pesos))
    metricas = modelo.val(data=str(args.datos), imgsz=args.imgsz, verbose=False)
    map50 = float(metricas.box.map50)
    millones, gflops = resumen(modelo, args.imgsz)
    print("\nCriterios del OE2 y RNF-11")
    print(f"  {'✓' if map50 >= 0.80 else '✗'} mAP@0,5 = {map50:.3f} (meta ≥ 0,80)")
    print(f"  {'✓' if millones <= 3 else '✗'} parámetros = {millones:.2f} M (máximo 3 M)")
    print(f"  {'✓' if gflops <= 5 else '✗'} GFLOPs = {gflops:.2f} a {args.imgsz} px (máximo 5)")
    for i, nombre in modelo.names.items():
        try:
            print(f"      AP@0,5 {nombre:<18} {float(metricas.box.ap50[i]):.3f}")
        except (IndexError, AttributeError):
            pass
    if args.medir_fps:
        fps = medir_fps(modelo, args.imgsz)
        print(f"  {'✓' if fps >= 15 else '✗'} {fps:.1f} fps en este equipo (mínimo 15, RNF-09)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

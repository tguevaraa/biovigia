#!/usr/bin/env python3
"""Comprueba que los videos base de BVIA-32 cumplen lo acordado.

Uso:
    python herramientas/verificar_videos.py
    python herramientas/verificar_videos.py --carpeta datos/videos
"""
import argparse
import pathlib
import sys

try:
    import cv2
except ImportError:
    sys.exit("Falta OpenCV. Instálalo con:  pip install -r requirements-vision.txt")

ESPERADO = {"rojo": 8, "comun": 8, "negativo": 2, "vacio": 2}
DURACION_MIN, DURACION_MAX = 7.0, 15.0
FPS_MIN = 24
ANCHO_MIN = 640


def tipo_de(nombre: str) -> str | None:
    for t in ESPERADO:
        if nombre.startswith(t):
            return t
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--carpeta", default="datos/videos")
    args = ap.parse_args()

    carpeta = pathlib.Path(args.carpeta)
    if not carpeta.is_dir():
        print(f"✗ No existe la carpeta {carpeta}")
        return 1

    videos = sorted(
        p for p in carpeta.iterdir()
        if p.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}
    )
    if not videos:
        print(f"✗ No hay videos en {carpeta}")
        return 1

    conteo = {t: 0 for t in ESPERADO}
    problemas: list[str] = []
    fotogramas_totales = 0

    print(f"{'archivo':<22}{'tipo':<11}{'dur.':>7}{'fps':>7}{'resolución':>13}")
    print("-" * 60)

    for v in videos:
        tipo = tipo_de(v.stem)
        cap = cv2.VideoCapture(str(v))
        if not cap.isOpened():
            problemas.append(f"{v.name}: no se puede abrir")
            continue
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()

        dur = n / fps if fps else 0
        fotogramas_totales += n
        if tipo:
            conteo[tipo] += 1
        else:
            problemas.append(
                f"{v.name}: el nombre no empieza por rojo_, comun_, negativo_ o vacio_")

        if not (DURACION_MIN <= dur <= DURACION_MAX):
            problemas.append(f"{v.name}: dura {dur:.1f} s (se esperaban ~10 s)")
        if fps < FPS_MIN:
            problemas.append(f"{v.name}: {fps:.0f} fps (mínimo {FPS_MIN})")
        if ancho < ANCHO_MIN:
            problemas.append(f"{v.name}: {ancho} px de ancho (mínimo {ANCHO_MIN})")

        print(f"{v.name:<22}{tipo or '?':<11}{dur:>6.1f}s{fps:>7.0f}{f'{ancho}x{alto}':>13}")

    print("-" * 60)
    for t, esperados in ESPERADO.items():
        hay = conteo[t]
        marca = "✓" if hay == esperados else "✗"
        print(f"  {marca} {t:<10} {hay} de {esperados}")
        if hay != esperados:
            problemas.append(f"faltan {esperados - hay} video(s) de tipo '{t}'")

    muestreados = fotogramas_totales // 10
    print(f"\n  {fotogramas_totales} fotogramas en total "
          f"→ ~{muestreados} imágenes muestreando 1 de cada 10")
    if muestreados < 400:
        problemas.append(
            f"solo saldrían ~{muestreados} imágenes; se necesitan al menos 400 (BVIA-38)")

    if problemas:
        print("\nProblemas que hay que resolver antes de cerrar BVIA-32:")
        for p in problemas:
            print(f"  ✗ {p}")
        return 1

    print("\n✓ Todo en orden. BVIA-32 se puede pasar a «En revisión».")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Graba clips cortos con la cámara, para marcarlos después con marcar_con_un_clic.py.

    python herramientas/grabar_clips.py                                   # → datos/videos/cuarto
    python herramientas/grabar_clips.py --salida datos/videos/laboratorio --prefijo lab
    python herramientas/grabar_clips.py --tomas cuerpo --prefijo cuerpo   # gasa delante del torso

Se abre una ventana con la cámara en vivo y, arriba, la toma sugerida que toca grabar:

* **Espacio** empieza a grabar y, otra vez, termina el clip (se guarda solo).
* **n** salta a la siguiente toma sugerida sin grabar · **q** o **Esc** sale.

Los clips se guardan a la resolución de la cámara, sin reducir, como ``<prefijo>_NN.mp4``
(sin pisar los que ya existan). Graba cada toma unos 10–20 s: que la gasa se vea entera
en algún momento, y sin tapar el lente.
"""
from __future__ import annotations

import argparse
import pathlib
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
VENTANA = "Grabar clips - Espacio graba/corta, n siguiente toma, q sale"

TOMAS = [
    "Gasa en la mano, cerca de la camara (1 m), girandola",
    "Gasa en la mano, lejos (otro lado del cuarto)",
    "Llevar la gasa al tacho y soltarla adentro",
    "Tirar la gasa al piso",
    "Gasa apoyada en la mesa o la cama, alguien pasa cerca",
    "Dos gasas a la vez, en las dos manos",
    "Con la luz apagada (o solo una lampara): gasa en la mano",
    "Con la luz apagada: llevar la gasa al tacho",
    "Otra persona sostiene la gasa",
    "Gasa doblada o arrugada, en la mano",
]

# Delante del cuerpo: la v0.4 no veía la gasa sobre el torso (0 de 16), sobre todo con ropa
# que tiene partes blancas. Conviene grabarlas con ropa distinta (lisa, con rayas, clara).
TOMAS_CUERPO = [
    "Gasa delante del pecho, quieta, de frente a la camara",
    "Pasar la gasa de una mano a la otra por delante del cuerpo",
    "Gasa a la altura de la cintura, caminando",
    "Gasa delante del pecho, de costado a la camara",
    "Llevar la gasa al tacho pasando por delante del cuerpo",
    "Otra persona: gasa delante del pecho",
]
LISTAS = {"general": TOMAS, "cuerpo": TOMAS_CUERPO}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fuente", type=int, default=0, help="Índice de cámara")
    ap.add_argument("--salida", type=pathlib.Path, default=RAIZ / "datos" / "videos" / "cuarto")
    ap.add_argument("--prefijo", default="cuarto")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--tomas", choices=sorted(LISTAS), default="general",
                    help="Lista de tomas sugeridas (cuerpo = gasa delante del torso)")
    args = ap.parse_args()

    import cv2

    args.salida.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(args.fuente, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    toma, escritor, inicio, ruta, n_fotogramas = 0, None, 0.0, None, 0

    def siguiente_ruta() -> pathlib.Path:
        k = 1
        while (args.salida / f"{args.prefijo}_{k:02d}.mp4").exists():
            k += 1
        return args.salida / f"{args.prefijo}_{k:02d}.mp4"

    print(f"Clips en {args.salida}. Espacio = grabar / cortar.", flush=True)
    try:
        while True:
            ok, img = cap.read()
            if not ok:
                cv2.waitKey(30)
                continue
            if escritor is not None:
                escritor.write(img)
                n_fotogramas += 1
            vista = cv2.resize(img, None, fx=1100 / img.shape[1], fy=1100 / img.shape[1])
            lista = LISTAS[args.tomas]
            texto = lista[toma % len(lista)]
            cv2.rectangle(vista, (0, 0), (vista.shape[1], 80), (0, 0, 0), -1)
            cv2.putText(vista, f"Toma {toma + 1}: {texto}", (12, 32), cv2.FONT_HERSHEY_SIMPLEX,
                        0.75, (0, 255, 255), 2)
            if escritor is not None:
                cv2.circle(vista, (25, 60), 9, (0, 0, 255), -1)
                cv2.putText(vista, f"GRABANDO {ruta.name}  {time.monotonic() - inicio:4.1f} s",
                            (42, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                cv2.putText(vista, "Espacio para grabar", (12, 68), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (255, 255, 255), 2)
            cv2.imshow(VENTANA, vista)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord(" "):
                if escritor is None:
                    ruta = siguiente_ruta()
                    h, w = img.shape[:2]
                    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (w, h))
                    inicio, n_fotogramas = time.monotonic(), 0
                else:
                    escritor.release()
                    escritor = None
                    duracion = time.monotonic() - inicio
                    print(f"  ✓ {ruta.name}: {duracion:.1f} s, {n_fotogramas} fotogramas · {texto}", flush=True)
                    toma += 1
            elif tecla == ord("n") and escritor is None:
                toma += 1
            elif tecla in (ord("q"), 27):
                break
    finally:
        if escritor is not None:
            escritor.release()
            print(f"  ✓ {ruta.name} (cortado al salir)", flush=True)
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

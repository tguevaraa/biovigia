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
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
# La consola de Windows (cp1252) no tiene ✓, ▸ ni →: se reemplazan en vez de cortar.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(errors="replace")
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
# Para cualquier otro objeto (jeringa, curita…): las mismas situaciones, sin nombrar la gasa.
TOMAS_OBJETO = [
    "Objeto en la mano, cerca de la camara, girandolo",
    "Objeto en la mano, lejos (otro lado de la sala)",
    "Llevar el objeto al tacho y soltarlo adentro",
    "Tirar el objeto al piso",
    "Objeto apoyado en la mesa, alguien pasa cerca",
    "Objeto delante del pecho, de frente a la camara",
    "Pasar el objeto de una mano a la otra por delante del cuerpo",
    "Con la luz apagada (o solo una lampara): objeto en la mano",
    "Otra persona sostiene el objeto",
    "Dos objetos a la vez, en las dos manos",
]
# Tubos de muestra: son transparentes, así que lo que más se ve es la tapa de color. Conviene
# que aparezcan tapas de varios colores (con un solo color, el modelo aprende "tapa morada"),
# el tubo agarrado de distintas formas y tubos en la gradilla.
TOMAS_TUBO = [
    "Tubo MORADO en la mano, cerca de la camara, girandolo",
    "Tubo AMARILLO en la mano, cerca de la camara, girandolo",
    "Tubo MORADO en la mano, lejos (otro lado de la sala)",
    "Tubo AMARILLO en la mano, lejos (otro lado de la sala)",
    "Llevar el tubo MORADO al tacho y soltarlo adentro",
    "Llevar el tubo AMARILLO al tacho y soltarlo adentro",
    "Tirar el tubo MORADO al piso",
    "Tirar el tubo AMARILLO al piso",
    "MORADO en una mano y AMARILLO en la otra, moviendolos",
    "Agarrar cada tubo por la tapa, colgando (primero MORADO, luego AMARILLO)",
    "Los dos tubos parados en un vaso, alguien pasa cerca",
    "Los dos tubos acostados en la mesa",
    "Tubo MORADO delante del pecho, de frente a la camara",
    "Tubo AMARILLO delante del pecho, de frente a la camara",
    "Luz apagada (o solo una lampara): un tubo en cada mano",
    "Otra persona sostiene los dos tubos",
]
# Segunda ronda de tubos: la v0.3 veía el tubo cayendo o en el piso solo en el 68 % de los
# fotogramas (al caer es chico y borroso). Estas tomas son solo de eso.
TOMAS_TUBO_PISO = [
    "Tirar el tubo MORADO al piso, cerca de la cama",
    "Tirar el tubo AMARILLO al piso, cerca de la cama",
    "Tirar el tubo MORADO al piso, cerca del escritorio",
    "Tirar el tubo AMARILLO al piso, cerca del escritorio",
    "Tubo MORADO quieto en el piso, acostado, 5 s (luego moverlo a otro sitio)",
    "Tubo AMARILLO quieto en el piso, acostado, 5 s (luego moverlo a otro sitio)",
    "Tirar los DOS tubos al piso a la vez y dejarlos ahi",
    "Recoger los dos tubos del piso y volver a tirarlos",
]
# Tercera ronda: agarres que tapan parte del tubo. La v0.6 lo perdía sostenido con un dedo
# en cada punta (la tapa de color, que es lo que más mira el modelo, queda tapada).
TOMAS_TUBO_AGARRES = [
    "Tubo MORADO con un dedo en cada punta (tapa tapada), moviendolo",
    "Tubo AMARILLO con un dedo en cada punta (tapa tapada), moviendolo",
    "Tubo MORADO con la tapa dentro del puño, solo se ve el cuerpo",
    "Tubo AMARILLO con la tapa dentro del puño, solo se ve el cuerpo",
    "Tubo entre dos dedos, como un cigarrillo (MORADO y luego AMARILLO)",
    "Tubo MORADO de cabeza (tapa abajo), caminando hacia el tacho",
    "Tubo AMARILLO de cabeza (tapa abajo), caminando hacia el tacho",
    "Cerca de una lampara o ventana (mucha luz): un tubo en cada mano",
]
# Negativas para el modelo de tubos: la v0.9 tomaba por tubo una gasa girando de canto (se ve
# como una tira blanca alargada). Sin ningún tubo a la vista.
TOMAS_TUBO_NO = [
    "SIN TUBOS: gasa girando de canto, cerca de la camara",
    "SIN TUBOS: gasa enrollada como un tubito, en la mano, girandola",
    "SIN TUBOS: gasa doblada en tira larga, moviendola",
    "SIN TUBOS: gasa de canto, lejos (otro lado de la sala)",
    "SIN TUBOS: llevar la gasa enrollada al tacho y soltarla",
    "SIN TUBOS: lapicero, marcador o cepillo de dientes en la mano, girandolo",
]
# Tachos propios: tachos-v0.2 (solo fotos de internet) no veía un tacho rojo cilíndrico liso.
# En cada toma tienen que verse LOS DOS tachos enteros al empezar (ahí se hace el clic).
TOMAS_TACHOS = [
    "Los DOS tachos quietos, nadie en la escena, 10 s",
    "Mover los tachos a otro sitio del piso (que se vean los dos al empezar)",
    "Tachos juntos, uno al lado del otro; luego separarlos",
    "Pasar caminando por delante de los tachos, tapandolos a medias",
    "Echar cosas al tacho ROJO y luego al COMUN",
    "Agacharse junto a los tachos, la mano encima de la boca",
    "Luz apagada (o solo una lampara): los dos tachos quietos",
    "Tachos cerca de la cama o del escritorio, con cosas alrededor",
    "Cambiar el tacho ROJO de lugar varias veces durante la toma",
    "Tachos lejos de la camara (al fondo del cuarto)",
]
# Prueba del servicio completo: con la cámara donde la usa el servicio, para medir qué tan
# seguido ve cada objeto (gasa, jeringa) desde la mano hasta el tacho.
TOMAS_PRUEBA = [
    "GASA: mostrarla cerca de la camara 3 s, caminar y tirarla al tacho ROJO",
    "JERINGA: mostrarla cerca de la camara 3 s, caminar y tirarla al tacho ROJO",
    "GASA: tirarla al tacho COMUN",
    "JERINGA: tirarla al tacho COMUN",
]
# Tubos con el montaje de la demostración (cámara a ~2 m, tachos abajo): la v0.10 casi no los
# veía junto a los tachos (8 px). Sin gasas ni jeringas a la vista.
TOMAS_TUBO_MONTAJE = [
    "Tubo MORADO: llevarlo a la boca del tacho ROJO, quieto 1 s, soltarlo",
    "Tubo AMARILLO: llevarlo a la boca del tacho ROJO, quieto 1 s, soltarlo",
    "Tubo MORADO: llevarlo a la boca del tacho COMUN y soltarlo",
    "Tubo AMARILLO: llevarlo a la boca del tacho COMUN y soltarlo",
    "Los DOS tubos en la mano, caminando entre la camara y los tachos",
    "Un tubo en cada mano a la altura de la cintura, junto a los tachos, girandolos",
]
LISTAS = {"general": TOMAS, "cuerpo": TOMAS_CUERPO, "objeto": TOMAS_OBJETO, "tubo": TOMAS_TUBO,
          "prueba": TOMAS_PRUEBA, "tubo-montaje": TOMAS_TUBO_MONTAJE,
          "tubo-piso": TOMAS_TUBO_PISO, "tubo-agarres": TOMAS_TUBO_AGARRES,
          "tubo-no": TOMAS_TUBO_NO, "tachos": TOMAS_TACHOS}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fuente", type=int, default=0, help="Índice de cámara")
    ap.add_argument("--salida", type=pathlib.Path, default=RAIZ / "datos" / "videos" / "cuarto")
    ap.add_argument("--prefijo", default="cuarto")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--tomas", choices=sorted(LISTAS), default="general",
                    help="Lista de tomas sugeridas: general (gasa), cuerpo (gasa delante del torso), "
                         "objeto (cualquier otro objeto: jeringa, curita…), tubo (tubos de muestra)")
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

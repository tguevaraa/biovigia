#!/usr/bin/env python3
"""Marca un objeto en todo un clip con UN clic: SAM 2 lo sigue fotograma a fotograma.

    python herramientas/marcar_con_un_clic.py                          # gasa en datos/videos/*.mp4
    python herramientas/marcar_con_un_clic.py --videos datos/videos/sala --clase gasa
    python herramientas/marcar_con_un_clic.py --repetir                # rehace con los clics guardados

Para qué: no hay imágenes públicas de gasas y los detectores por texto (YOLO-World, YOLOE)
no encuentran una gasa doblada en la mano. Alguien tiene que decir dónde está, pero basta
una vez por clip: SAM 2 (Meta, vía Ultralytics) recibe ese clic y la sigue por el resto
del clip, aunque se mueva, se acerque o caiga al tacho.

Cómo se usa, en cada clip:

1. Mueve la barra hasta un fotograma en que se vea bien la gasa (SAM la sigue hacia
   adelante y hacia atrás desde ahí).
2. Haz UN clic sobre CADA gasa que se vea EN ESE FOTOGRAMA (no sobre la mano): cada clic es
   una gasa distinta. Si mueves la barra después, los clics se borran.
3. Enter = seguirla · r = borrar los clics · s = saltar el clip (no hay gasa) · Esc = terminar.

Los clics se guardan en ``<salida>/clics.json``: con ``--repetir`` se vuelve a generar todo
sin clics (por ejemplo con otro modelo de SAM o con otro paso entre fotogramas).

Se descartan los fotogramas en que SAM pierde el objeto (máscara vacía) o salta a algo
grande (más de ``--area-max`` de la imagen: la mano, el tacho). Salida en formato YOLO,
con las imágenes a 1024 px de lado mayor, partida por clip en ``train`` y ``val`` (los
clips de ``--val`` van a validación). Revisa ``<salida>/muestra.jpg`` antes de entrenar.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import shutil
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
# La consola de Windows (cp1252) no tiene ✓, ▸ ni →: se reemplazan en vez de cortar.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(errors="replace")
VENTANA = "Clic sobre el objeto - Enter sigue, r borra, s salta, Esc termina"


def elegir_clic(ruta: pathlib.Path, cv2) -> tuple[int, list[list[int]]] | None | str:
    """Ventana con barra de fotogramas. Devuelve (fotograma, puntos), None si se salta, o
    "salir"."""
    cap = cv2.VideoCapture(str(ruta))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    estado = {"i": 0, "puntos": []}
    escala = 1100 / cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    leido = {"i": -1, "img": None}

    def al_hacer_clic(evento, x, y, *_):
        if evento == cv2.EVENT_LBUTTONDOWN:
            estado["puntos"].append([round(x / escala), round(y / escala)])

    cv2.namedWindow(VENTANA)
    cv2.setMouseCallback(VENTANA, al_hacer_clic)
    def al_mover_barra(v):
        # Todos los clics tienen que ser del MISMO fotograma: SAM los aplica a ese. Si se
        # mueve la barra después de marcar, los clics quedarían sobre otra imagen.
        if v != estado["i"]:
            estado.update(i=v, puntos=[])

    cv2.createTrackbar("fotograma", VENTANA, 0, max(1, total - 1), al_mover_barra)
    try:
        while True:
            if leido["i"] != estado["i"]:          # leer solo si se movió la barra
                cap.set(cv2.CAP_PROP_POS_FRAMES, estado["i"])
                ok, img = cap.read()
                leido.update(i=estado["i"], img=img if ok else None)
            img = leido["img"]
            vista = cv2.resize(img, None, fx=escala, fy=escala) if img is not None else None
            if vista is not None:
                for n, (x, y) in enumerate(estado["puntos"], 1):
                    p = (round(x * escala), round(y * escala))
                    cv2.circle(vista, p, 7, (0, 255, 255), 2)
                    cv2.putText(vista, str(n), (p[0] + 9, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, (0, 255, 255), 2)
                cv2.putText(vista, f"{ruta.name}  fotograma {estado['i']}/{total - 1}", (15, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                ayuda = (f"{len(estado['puntos'])} gasa(s) en ESTE fotograma - Enter confirma "
                         "(mover la barra borra los clics)"
                         if estado["puntos"] else "Elige UN fotograma y haz un clic por cada gasa que se vea")
                cv2.putText(vista, ayuda, (15, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                cv2.imshow(VENTANA, vista)
            tecla = cv2.waitKey(30) & 0xFF
            if tecla == 13 and estado["puntos"]:
                return estado["i"], estado["puntos"]
            if tecla == ord("r"):
                estado["puntos"] = []
            if tecla == ord("s"):
                return None
            if tecla == 27:
                return "salir"
    finally:
        cap.release()
        cv2.destroyWindow(VENTANA)


def seguir(ruta: pathlib.Path, desde: int, puntos: list[list[int]], args, cv2, np):
    """Corre SAM 2 desde el fotograma ``desde`` hacia adelante y hacia atrás, y devuelve
    [(n.º de fotograma, imagen, [cajas xyxy])]. SAM 2 solo acepta el clic en el primer
    fotograma del video, así que el tramo anterior se le pasa al revés."""
    cap = cv2.VideoCapture(str(ruta))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    ancho, alto = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    f = 1024 / max(ancho, alto)
    todos: dict[int, np.ndarray] = {}
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if (i - desde) % args.paso == 0 and abs(i - desde) <= args.max_fotogramas * args.paso:
            todos[i] = cv2.resize(img, (round(ancho * f), round(alto * f)), interpolation=cv2.INTER_AREA)
        i += 1
    cap.release()
    if desde not in todos:
        return []
    adelante = sorted(n for n in todos if n >= desde)
    atras = sorted((n for n in todos if n <= desde), reverse=True)
    pts = [[round(x * f), round(y * f)] for x, y in puntos]
    salida = _sam(adelante, todos, pts, fps / args.paso, args, cv2, np)
    if len(atras) > 1:
        salida += _sam(atras, todos, pts, fps / args.paso, args, cv2, np)[1:]  # sin repetir el clic
    return sorted(salida, key=lambda s: s[0])


def caja_de_mascara(m, h, w, args, cv2, np):
    """Caja de la parte principal de la máscara, o None si no parece un objeto compacto.

    SAM a veces devuelve una máscara salpicada (pedazos de papel sueltos dentro del tacho):
    pocos píxeles, pero una caja que abarca medio tacho. Por eso se toma solo la mancha más
    grande y se descarta si la caja es grande o si la mancha llena poco de su caja."""
    m = m.astype(np.uint8)
    if m.shape != (h, w):
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh, area = stats[k]
    if bw * bh > args.area_max * h * w or area < args.relleno_min * bw * bh or area < 30:
        return None
    if max(bw / bh, bh / bw) >= 3:      # una tira (el borde de un tacho), no una gasa
        return None
    return float(x), float(y), float(x + bw), float(y + bh)


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _sam(numeros, todos, pts, fps, args, cv2, np):
    from ultralytics.models.sam import SAM2VideoPredictor

    temporal = pathlib.Path(tempfile.mkdtemp())
    try:
        video = temporal / "tramo.mp4"
        h, w = todos[numeros[0]].shape[:2]
        escritor = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for n in numeros:
            escritor.write(todos[n])
        escritor.release()
        predictor = SAM2VideoPredictor(overrides=dict(conf=0.25, task="segment", mode="predict",
                                                      imgsz=1024, model=args.sam, verbose=False,
                                                      save=False))
        # Cada clic es un objeto distinto (una gasa): SAM 2 sigue cada uno por separado.
        salida = []
        referencia: dict[int, float] = {}   # área de cada objeto en el fotograma del clic
        for k, r in enumerate(predictor(source=str(video), points=pts, labels=[1] * len(pts),
                                        stream=True)):
            cajas = []
            if r.masks is not None:
                for j, m in enumerate(r.masks.data.cpu().numpy()):
                    caja = caja_de_mascara(m, h, w, args, cv2, np)
                    if caja is None:
                        continue
                    area = (caja[2] - caja[0]) * (caja[3] - caja[1])
                    if k == 0:
                        referencia[j] = area
                    # Si el objeto no estaba bien marcado en el clic, o su tamaño cambia mucho,
                    # SAM se pasó a otra cosa (el borde del tacho, un pedazo de papel).
                    if j not in referencia or not (args.cambio_max ** -1 <= area / referencia[j]
                                                   <= args.cambio_max):
                        continue
                    if all(_iou(caja, c) < 0.5 for c in cajas):
                        cajas.append(caja)
            salida.append((numeros[k], todos[numeros[k]], cajas))
        return salida
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", type=pathlib.Path, default=RAIZ / "datos" / "videos")
    ap.add_argument("--patron", default="*.mp4")
    ap.add_argument("--salida", type=pathlib.Path, default=RAIZ / "datos" / "externos" / "gasas-propias")
    ap.add_argument("--clase", default="gasa")
    ap.add_argument("--val", nargs="*", default=["rojo_08", "comun_08"],
                    help="Clips (sin extensión) que van a validación")
    ap.add_argument("--paso", type=int, default=3, help="Usar 1 de cada N fotogramas")
    ap.add_argument("--max-fotogramas", type=int, default=200, help="Por clip, hacia cada lado del clic")
    ap.add_argument("--area-max", type=float, default=0.02,
                    help="Caja máxima, en fracción de la imagen")
    ap.add_argument("--relleno-min", type=float, default=0.3,
                    help="Fracción mínima de la caja que debe cubrir la máscara")
    ap.add_argument("--cambio-max", type=float, default=2.5,
                    help="Cuántas veces puede crecer o achicarse la caja respecto del clic")
    ap.add_argument("--sam", default="sam2.1_b.pt", help="Pesos de SAM 2 (se descargan solos)")
    ap.add_argument("--repetir", action="store_true", help="No pedir clics: usar clics.json")
    ap.add_argument("--solo", nargs="*", help="Procesar solo estos clips (sin extensión)")
    args = ap.parse_args()

    import cv2
    import numpy as np

    args.salida.mkdir(parents=True, exist_ok=True)
    archivo_clics = args.salida / "clics.json"
    clics = json.loads(archivo_clics.read_text(encoding="utf-8")) if archivo_clics.exists() else {}
    videos = sorted(args.videos.glob(args.patron))
    if args.solo:
        videos = [v for v in videos if v.stem in args.solo]

    if not args.repetir:
        for v in videos:
            if v.stem in clics:
                continue
            r = elegir_clic(v, cv2)
            if r == "salir":
                break
            clics[v.stem] = None if r is None else {"fotograma": r[0], "puntos": r[1]}
            archivo_clics.write_text(json.dumps(clics, indent=2), encoding="utf-8")
            print(f"  {v.stem}: " + ("saltado" if r is None else
                                     f"{len(r[1])} clic(s) en el fotograma {r[0]}"), flush=True)

    muestras = []
    for v in videos:
        c = clics.get(v.stem)
        if not c:
            continue
        particion = "val" if v.stem in args.val else "train"
        (args.salida / particion / "images").mkdir(parents=True, exist_ok=True)
        (args.salida / particion / "labels").mkdir(parents=True, exist_ok=True)
        resultado = seguir(v, c["fotograma"], c["puntos"], args, cv2, np)
        guardados = total_cajas = 0
        for numero, img, cajas in resultado:
            if not cajas:
                continue
            h, w = img.shape[:2]
            nombre = f"{v.stem}_{numero:05d}"
            cv2.imwrite(str(args.salida / particion / "images" / f"{nombre}.jpg"), img,
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            (args.salida / particion / "labels" / f"{nombre}.txt").write_text("".join(
                f"0 {(x0 + x1) / 2 / w:.6f} {(y0 + y1) / 2 / h:.6f} {(x1 - x0) / w:.6f} {(y1 - y0) / h:.6f}\n"
                for x0, y0, x1, y1 in cajas), encoding="utf-8")
            guardados += 1
            total_cajas += len(cajas)
            if guardados % 15 == 1:
                vista = img.copy()
                for x0, y0, x1, y1 in cajas:
                    cv2.rectangle(vista, (int(x0), int(y0)), (int(x1), int(y1)), (255, 255, 0), 3)
                cv2.putText(vista, nombre, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                muestras.append(cv2.resize(vista, (480, round(480 * h / w))))
        print(f"  {v.stem}: {guardados} de {len(resultado)} fotogramas con {args.clase}, "
              f"{total_cajas} cajas ({particion})", flush=True)

    if muestras:
        alto = min(m.shape[0] for m in muestras)
        muestras = [m[:alto] for m in muestras][:24]
        while len(muestras) % 4:
            muestras.append(np.zeros_like(muestras[0]))
        filas = [np.hstack(muestras[i:i + 4]) for i in range(0, len(muestras), 4)]
        cv2.imwrite(str(args.salida / "muestra.jpg"), np.vstack(filas))
        print(f"✓ Muestra en {args.salida / 'muestra.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

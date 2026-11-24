#!/usr/bin/env python3
"""Muestra en vivo lo que reconoce un modelo, sin eventos ni servidor (modo demostración).

    python herramientas/probar_modelo.py                                   # tachos + personas, cámara 0
    python herramientas/probar_modelo.py --modelo vision/modelos/otro.pt --fuente 1
    python herramientas/probar_modelo.py --fuente datos/videos/rojo_01.mp4 --confianza 0.4
    python herramientas/probar_modelo.py --sin-estabilizar                 # cajas crudas, para comparar
    python herramientas/probar_modelo.py --objeto vision/modelos/biovigia-jeringas-v0.1.pt

Las cajas se estabilizan en el tiempo (vision/estabilizador.py): no parpadean cuando la
confianza ronda el umbral y se mantienen un momento si una mano tapa el tacho (línea fina).

Sirve para ver desde qué ángulo y a qué distancia el modelo encuentra los tachos y las
personas, con el teléfono fijo o en la mano. Usa la misma captura que el servicio de
visión (resolución nativa, sin deformar). Tecla q o Esc para salir.
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
sys.path.insert(0, str(RAIZ))

try:
    import cv2
    from ultralytics import YOLO

    from vision.captura import crear_fuente
    from vision.estabilizador import Estabilizador
    from vision.recortes import buscar_en_recortes, region_de_busqueda
    from vision.tipos import Deteccion
except ImportError:
    sys.exit("Faltan dependencias: pip install -r requirements-vision.txt")

COLORES = {"recipiente": (60, 60, 255), "persona": (255, 170, 0), "gasa": (255, 255, 0)}
VENTANA = "BioVigIA - prueba del modelo"


def _iou(a, b) -> float:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    union = (a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter
    return inter / union if union else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", type=pathlib.Path,
                    default=RAIZ / "vision" / "modelos" / "biovigia-tachos-v0.2.pt")
    ap.add_argument("--modelo-gasas", type=pathlib.Path,
                    default=RAIZ / "vision" / "modelos" / "biovigia-gasas-v0.5.pt",
                    help="Modelo de gasas (si existe se usa también)")
    ap.add_argument("--objeto", type=pathlib.Path, action="append", default=[],
                    help="Otro modelo de un objeto chico (jeringas, curitas…); se puede repetir. "
                         "La etiqueta es el nombre de clase del modelo")
    ap.add_argument("--modelo-personas", type=pathlib.Path,
                    default=RAIZ / "vision" / "modelos" / "yolo11n-coco.pt",
                    help="YOLO original (COCO) para las personas; vacío = no usarlo")
    ap.add_argument("--fuente", default="0", help="Índice de cámara, video o rtsp://…")
    ap.add_argument("--confianza", type=float, default=0.35,
                    help="Confianza para que aparezca un objeto nuevo")
    # Con biovigia-gasas-v0.1 los recortes no encontraron ninguna gasa más y sí sumaron
    # falsos positivos (medición del 22/11/2026): quedan apagados hasta tener el modelo
    # entrenado con gasas reales.
    ap.add_argument("--con-recortes", action="store_true",
                    help="Busca las gasas también en recortes alrededor de personas y tachos (etapa 2)")
    ap.add_argument("--area-max-gasa", type=float, default=0.02,
                    help="Descarta «gasas» más grandes que esta fracción de la imagen; no se "
                         "aplica a los modelos de --objeto "
                         "(el modelo actual suele encuadrar la mano entera)")
    ap.add_argument("--sin-estabilizar", action="store_true",
                    help="Dibuja lo que da el modelo en cada fotograma (parpadea)")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--ancho-ventana", type=int, default=1280)
    args = ap.parse_args()

    if not args.modelo.exists():
        print(f"✗ No existe {args.modelo}")
        return 1
    modelo = YOLO(str(args.modelo))
    personas = None
    if str(args.modelo_personas) and args.modelo_personas.exists():
        personas = YOLO(str(args.modelo_personas))
    # Objetos chicos que se mueven con la mano: la gasa y los que agregue el equipo.
    objetos = []
    for ruta in ([args.modelo_gasas] if str(args.modelo_gasas) else []) + args.objeto:
        if ruta.exists():
            objetos.append(YOLO(str(ruta)))
        else:
            print(f"✗ No existe {ruta}; se sigue sin él")
    clases_objeto = {n for m in objetos for n in m.names.values()}
    # El límite de área es para la gasa (su modelo encuadraba la mano entera). Una jeringa
    # cerca de la cámara ocupa más del 2 % y el límite la borraba.
    clases_con_limite = ({n for n in objetos[0].names.values()}
                         if objetos and str(args.modelo_gasas) and args.modelo_gasas.exists() else set())
    estabilizador = None if args.sin_estabilizar else Estabilizador(
        umbral_alta=args.confianza, umbral_baja=min(0.15, args.confianza))
    fuente = crear_fuente(args.fuente, 640, 480, 30)
    previo, fps = time.monotonic(), 0.0
    try:
        while True:
            f = fuente.leer()
            if f is None:
                if fuente.terminada:
                    break
                continue
            imagen = (f.original if f.original is not None else f.imagen).copy()
            # Con estabilizador se pide al modelo hasta la confianza baja: los objetos ya
            # conocidos se mantienen con ella, los nuevos necesitan --confianza.
            minima = args.confianza if estabilizador is None else estabilizador.umbral_baja
            detecciones = []
            r = modelo.predict(imagen, conf=minima, imgsz=args.imgsz, verbose=False)[0]
            detecciones += [Deteccion(r.names[int(k)], c, *xyxy) for xyxy, c, k in
                            zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(),
                                r.boxes.cls.tolist())]
            if personas is not None:  # COCO: la clase 0 es «person»
                rp = personas.predict(imagen, conf=minima, imgsz=args.imgsz,
                                      classes=[0], verbose=False)[0]
                detecciones += [Deteccion("persona", c, *xyxy) for xyxy, c in
                                zip(rp.boxes.xyxy.tolist(), rp.boxes.conf.tolist())]
            if objetos:
                def detectar_gasas(recorte):
                    halladas = []
                    for m in objetos:
                        rg = m.predict(recorte, conf=minima, imgsz=args.imgsz, verbose=False)[0]
                        halladas += [Deteccion(rg.names[int(k)], c, *xyxy) for xyxy, c, k in
                                     zip(rg.boxes.xyxy.tolist(), rg.boxes.conf.tolist(),
                                         rg.boxes.cls.tolist())]
                    if len(objetos) == 1:
                        return halladas
                    # Varios modelos del mismo objeto (p. ej. jeringas v0.6 + v0.7): se queda
                    # la caja más segura de cada grupo que se solapa, como un NMS a 0,5.
                    unicas = []
                    for d in sorted(halladas, key=lambda d: -d.confianza):
                        if all(u.clase != d.clase or _iou(u, d) < 0.5 for u in unicas):
                            unicas.append(d)
                    return unicas

                encontradas = detectar_gasas(imagen)
                if args.con_recortes:
                    # Etapa 2: la gasa también se busca en recortes del original alrededor de
                    # personas y tachos, donde queda varias veces más grande (vision/recortes.py).
                    guias = [d for d in detecciones if d.clase in ("persona", "recipiente")
                             and d.confianza >= args.confianza]
                    for g in guias:
                        x0, y0, x1, y1 = region_de_busqueda(g, imagen.shape[1], imagen.shape[0])
                        cv2.rectangle(imagen, (x0, y0), (x1, y1), (120, 120, 120), 1)
                    encontradas = buscar_en_recortes(imagen, guias, detectar_gasas) + encontradas
                limite = args.area_max_gasa * imagen.shape[0] * imagen.shape[1]
                detecciones += [d for d in encontradas if d.clase not in clases_con_limite
                                or (d.x1 - d.x0) * (d.y1 - d.y0) <= limite]
            if estabilizador is None:
                dibujar = [(d, False) for d in detecciones]
            else:
                # El estabilizador es para objetos casi quietos (tachos, personas). Una gasa
                # (o una jeringa) se mueve rápido: retenerla deja una estela de cajas viejas.
                dibujar = [(o.caja, o.retenido(f.t)) for o in estabilizador.actualizar(
                    [d for d in detecciones if d.clase not in clases_objeto], f.t)]
                dibujar += [(d, False) for d in detecciones
                            if d.clase in clases_objeto and d.confianza >= args.confianza]
            cuenta: dict[str, int] = {}
            for d, retenida in dibujar:
                cuenta[d.clase] = cuenta.get(d.clase, 0) + 1
                color = COLORES.get(d.clase, (0, 220, 0))
                p0, p1 = (int(d.x0), int(d.y0)), (int(d.x1), int(d.y1))
                # Línea fina = el modelo no lo vio en este fotograma y se mantiene por retención.
                cv2.rectangle(imagen, p0, p1, color, 1 if retenida else 3)
                cv2.putText(imagen, f"{d.clase} {d.confianza:.2f}", (p0[0], max(30, p0[1] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
            ahora = time.monotonic()
            fps = 0.9 * fps + 0.1 / max(ahora - previo, 1e-3)
            previo = ahora
            resumen = "  ".join(f"{n}: {v}" for n, v in sorted(cuenta.items())) or "nada"
            cv2.putText(imagen, f"{fps:.0f} fps | {resumen}", (20, 45),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
            escala = args.ancho_ventana / imagen.shape[1]
            cv2.imshow(VENTANA, cv2.resize(imagen, None, fx=escala, fy=escala))
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        fuente.cerrar()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Llena el tablero con eventos de prueba, sin cámara (contrato v1, POST /api/v1/eventos).

También informa el tramo observado para que el tablero no marque el turno como «sin
observar». Los eventos llevan el modelo «simulador» para reconocerlos y borrarlos.

    python herramientas/simulador.py --n 20
    python herramientas/simulador.py --n 10 --proporcion-comun 0.5 --token <token>
    python herramientas/simulador.py --repetir      # reenvía el último lote: prueba de duplicados

El token se toma de --token, de BIOVIGIA_TOKEN o de vision/.env.
"""
from __future__ import annotations

import argparse
import base64
import os
import pathlib
import random
import sys
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    sys.exit("Falta requests: pip install requests")

RAIZ = pathlib.Path(__file__).resolve().parents[1]
ULTIMO_LOTE = RAIZ / "herramientas" / ".ultimo_lote_simulador"


def token_por_defecto() -> str:
    if os.environ.get("BIOVIGIA_TOKEN"):
        return os.environ["BIOVIGIA_TOKEN"]
    env = RAIZ / "vision" / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if linea.strip().startswith("BIOVIGIA_TOKEN="):
                return linea.split("=", 1)[1].strip()
    return ""


def recorte_jpeg() -> str | None:
    """Recorte sintético del recipiente común con una gasa (si hay OpenCV)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    img = np.full((120, 180, 3), (35, 35, 35), np.uint8)
    cv2.rectangle(img, (0, 0), (179, 25), (20, 20, 20), -1)
    cv2.ellipse(img, (90 + random.randint(-30, 30), 70), (16, 11), 20, 0, 360, (245, 245, 245), -1)
    ok, buf = cv2.imencode(".jpg", img)
    return base64.b64encode(buf.tobytes()).decode() if ok else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulador de eventos de BioVigIA")
    ap.add_argument("--n", type=int, default=20, help="Cantidad de eventos (por defecto 20)")
    ap.add_argument("--servidor", default=os.environ.get("BIOVIGIA_SERVIDOR",
                                                         "http://localhost:8000"))
    ap.add_argument("--token", default=token_por_defecto())
    ap.add_argument("--box", default="box-2")
    ap.add_argument("--minutos", type=int, default=120,
                    help="Reparte los eventos en los últimos N minutos (por defecto 120)")
    ap.add_argument("--proporcion-comun", type=float, default=0.15,
                    help="Fracción de descartes al recipiente común (no conformes)")
    ap.add_argument("--repetir", action="store_true",
                    help="Reenvía el último lote: todos deben volver como duplicados (200)")
    args = ap.parse_args()

    if not args.token:
        print("✗ Falta el token. Obtenlo con:  python servidor/manage.py token_vision")
        return 2
    sesion = requests.Session()
    sesion.headers["Authorization"] = f"Token {args.token}"
    base = args.servidor.rstrip("/") + "/api/v1"

    ahora = datetime.now().astimezone()
    if args.repetir:
        if not ULTIMO_LOTE.exists():
            print("✗ No hay un lote anterior que repetir")
            return 1
        import json

        lote = json.loads(ULTIMO_LOTE.read_text(encoding="utf-8"))
    else:
        lote = []
        for i in range(args.n):
            momento = ahora - timedelta(minutes=random.uniform(0.5, args.minutos))
            recipiente = "comun" if random.random() < args.proporcion_comun else "rojo"
            cuerpo = {
                "id_externo": f"sim-{args.box.replace('-', '')}-"
                              f"{momento:%Y%m%dT%H%M%S}.{momento.microsecond // 1000:03d}-{i}",
                "box": args.box,
                "recipiente": recipiente,
                "veredicto": "conforme" if recipiente == "rojo" else "no_conforme",
                "confianza": round(random.uniform(0.82, 0.99), 3),
                "ocurrido_en": momento.isoformat(timespec="milliseconds"),
                "modelo": "simulador",
                "rasgos": {"fotogramas_confirmacion": random.randint(3, 5),
                           "duracion_s": round(random.uniform(0.6, 2.5), 2),
                           "simulado": True},
            }
            if recipiente == "comun":
                evidencia = recorte_jpeg()
                if evidencia:
                    cuerpo["evidencia_jpeg_b64"] = evidencia
            lote.append(cuerpo)
        lote.sort(key=lambda c: c["ocurrido_en"])

    # Tramo observado que cubre el lote, para que el tablero muestre las horas como observadas.
    inicio = min(datetime.fromisoformat(c["ocurrido_en"]) for c in lote) - timedelta(minutes=1)
    try:
        r = sesion.post(f"{base}/salud", json={
            "box": args.box, "camara_conectada": True, "fps": 15.0, "modelo": "simulador",
            "tramos": [{"inicio": inicio.isoformat(), "fin": ahora.isoformat()}]}, timeout=10)
    except requests.RequestException as exc:
        print(f"✗ No hay conexión con {args.servidor}: {exc.__class__.__name__}")
        return 1
    if r.status_code == 401:
        print("✗ Token rechazado (401)")
        return 1

    creados = duplicados = errores = 0
    for cuerpo in lote:
        r = sesion.post(f"{base}/eventos", json=cuerpo, timeout=10)
        if r.status_code == 201:
            creados += 1
        elif r.status_code == 200:
            duplicados += 1
        else:
            errores += 1
            print(f"  ✗ {cuerpo['id_externo']}: {r.status_code} {r.text[:200]}")
    if not args.repetir:
        import json

        ULTIMO_LOTE.write_text(json.dumps(lote), encoding="utf-8")
    nc = sum(1 for c in lote if c["recipiente"] == "comun")
    print(f"✓ {creados} creados · {duplicados} duplicados · {errores} con error "
          f"({len(lote) - nc} al rojo, {nc} al común)")
    return 0 if errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

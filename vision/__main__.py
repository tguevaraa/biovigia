"""Punto de entrada:  python -m vision  (desde la raíz del repositorio).

Ejemplos:
    python -m vision --mostrar                         # cámara 0, publica en el servidor
    python -m vision --fuente datos/videos/comun_01.mp4 --sin-servidor --mostrar
    python -m vision --detector movimiento --mostrar   # sin modelo entrenado (desarrollo)
    python -m vision --enviar-referencia               # fotograma de la escena vacía → PAN-09
    python -m vision --editar-zonas                    # editor local de zonas
"""
from __future__ import annotations

import base64
import logging
import signal
import sys

import cv2

from .captura import crear_fuente, listar_camaras
from .cliente_api import ClienteAPI
from .cola import ColaLocal
from .configuracion import aplicar_argumentos, argumentos, desde_entorno
from .deteccion import ErrorModelo, crear_detector
from .editor_zonas import capturar_referencia, editar
from .metricas import crear_metricas
from .pipeline import ServicioVision
from .publicador import Publicador
from .zonas import ConjuntoZonas

log = logging.getLogger("vision")

AYUDA_CAMARA = (
    "Revisa: (1) que la cámara esté conectada y ninguna otra app la use (Zoom, Teams, la "
    "app Cámara); (2) Configuración de Windows → Privacidad → Cámara → permitir a las apps "
    "de escritorio; (3) prueba otro índice con  python -m vision --listar-camaras  y "
    "--fuente 1. Sin cámara, puedes usar el celular (URL http://… de DroidCam o IP Webcam) "
    "o un video:  --fuente datos/videos/comun_01.mp4")


def _configurar_registro(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for ruidoso in ("urllib3", "ultralytics", "botocore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    args = argumentos().parse_args(argv)
    _configurar_registro(args.verbose)
    config = aplicar_argumentos(desde_entorno(), args)

    if args.listar_camaras:
        camaras = listar_camaras()
        if not camaras:
            log.error("No se encontró ninguna cámara. %s", AYUDA_CAMARA)
            return 1
        for indice, ancho, alto in camaras:
            log.info("Cámara %s: %sx%s  →  BIOVIGIA_FUENTE=%s", indice, ancho, alto, indice)
        return 0

    if args.editar_zonas:
        try:
            return 0 if editar(config) else 1
        except RuntimeError as exc:
            log.error("%s. %s", exc, AYUDA_CAMARA)
            return 1

    necesita_servidor = not args.sin_servidor
    if necesita_servidor and not config.token:
        log.error("Falta BIOVIGIA_TOKEN en vision/.env. Obtenlo con:  "
                  "python servidor/manage.py token_vision --box %s   "
                  "(o usa --sin-servidor para probar sin publicar)", config.box)
        return 2
    cliente = ClienteAPI(config.servidor, config.token, config.verify) if necesita_servidor \
        else None

    if args.enviar_referencia:
        if cliente is None:
            log.error("--enviar-referencia necesita el servidor")
            return 2
        try:
            imagen = capturar_referencia(config)
        except RuntimeError as exc:
            log.error("%s. %s", exc, AYUDA_CAMARA)
            return 1
        ok, jpeg = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 90])
        r = cliente.enviar_referencia(config.box, base64.b64encode(jpeg.tobytes()).decode())
        if r.aceptado:
            log.info("Fotograma de referencia enviado. Traza las zonas en PAN-09 "
                     "(Configuración → Zonas de recipientes).")
            return 0
        log.error("El servidor no aceptó la referencia: %s", r.error)
        return 1

    zonas = ConjuntoZonas.cargar(config.archivo_zonas)
    if cliente is not None:
        remota = cliente.obtener_configuracion(config.box)
        if remota.aceptado and remota.datos:
            config.parametros.actualizar(remota.datos.get("parametros") or {})
            desde_servidor = ConjuntoZonas.desde_dict(remota.datos.get("zonas") or {})
            if desde_servidor:
                zonas = desde_servidor
                zonas.guardar(config.archivo_zonas, config.box)
        elif remota.estado == 401:
            log.error("El servidor rechazó el token (401). Revisa BIOVIGIA_TOKEN.")
            return 2
        else:
            log.warning("Servidor no disponible (%s). Se usan las zonas y parámetros locales; "
                        "los eventos quedarán en la cola hasta que vuelva.", remota.error)

    try:
        detector = crear_detector(config.detector, config.modelo,
                                  config.parametros.umbral_confianza, config.imgsz)
    except ErrorModelo as exc:
        log.error("%s", exc)
        return 2

    try:
        fuente = crear_fuente(config.fuente, config.ancho, config.alto,
                              config.parametros.fps_muestreo)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2

    cola = ColaLocal(config.dir_cola / f"{config.box}.sqlite3") if cliente else None
    servicio = ServicioVision(config, fuente, detector, zonas, cola=cola)
    publicador = None
    if cliente is not None and cola is not None:
        publicador = Publicador(cliente, cola, config.box, servicio.estado,
                                servicio.aplicar_configuracion,
                                crear_metricas(config.cloudwatch, config.box,
                                               config.cloudwatch_region),
                                config.intervalo_latido_s, config.intervalo_config_s)
        servicio.publicador = publicador
        publicador.iniciar()
        pendientes = cola.pendientes()
        if pendientes:
            log.info("%s evento(s) pendiente(s) en la cola local; se enviarán ahora", pendientes)

    def al_senal(*_):
        servicio.detener()

    signal.signal(signal.SIGINT, al_senal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, al_senal)

    try:
        eventos = servicio.ejecutar()
    finally:
        fuente.cerrar()
        if publicador is not None:
            publicador.detener()
            restantes = cola.pendientes()
            if restantes:
                log.warning("%s evento(s) siguen en la cola local y se enviarán en el próximo "
                            "arranque", restantes)
    log.info("Fin: %s descarte(s) confirmado(s)", len(eventos))
    return 0


if __name__ == "__main__":
    sys.exit(main())

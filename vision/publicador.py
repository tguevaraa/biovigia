"""Publicación: envía la cola de eventos, los latidos de salud y trae la configuración.

Corre en hilos aparte para que una red lenta nunca frene la captura ni la detección.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from .cliente_api import ClienteAPI
from .cola import ColaLocal
from .metricas import Metricas

log = logging.getLogger("vision.publicador")


class RegistroObservacion:
    """Lleva el tramo en el que la cámara está observando, para informar lo no observado."""

    def __init__(self, cola: ColaLocal) -> None:
        self.cola = cola
        self._candado = threading.Lock()
        self.inicio: Optional[datetime] = None
        self.ultimo: Optional[datetime] = None

    def observando(self, momento: datetime) -> None:
        with self._candado:
            if self.inicio is None:
                self.inicio = momento
            self.ultimo = momento

    def interrumpido(self) -> None:
        """La cámara dejó de entregar: el tramo abierto se cierra y queda en la cola."""
        with self._candado:
            if self.inicio is not None and self.ultimo is not None and self.ultimo > self.inicio:
                self.cola.guardar_tramo(self.inicio, self.ultimo)
            self.inicio = self.ultimo = None

    def abierto(self) -> Optional[dict]:
        with self._candado:
            if self.inicio is None or self.ultimo is None or self.ultimo <= self.inicio:
                return None
            return {"inicio": self.inicio.isoformat(), "fin": self.ultimo.isoformat()}


class Publicador:
    def __init__(self, cliente: ClienteAPI, cola: ColaLocal, box: str,
                 estado: Callable[[], dict], al_recibir_config: Callable[[dict], None],
                 metricas: Metricas, intervalo_latido_s: float = 10.0,
                 intervalo_config_s: float = 30.0) -> None:
        self.cliente = cliente
        self.cola = cola
        self.box = box
        self.estado = estado
        self.al_recibir_config = al_recibir_config
        self.metricas = metricas
        self.intervalo_latido_s = intervalo_latido_s
        self.intervalo_config_s = intervalo_config_s
        self.observacion = RegistroObservacion(cola)
        self._detener = threading.Event()
        self._hilos: list[threading.Thread] = []
        self.latencia_ms: Optional[float] = None
        self.conectado = False
        self._arranque = time.monotonic()

    def iniciar(self) -> None:
        for nombre, objetivo in (("eventos", self._bucle_eventos), ("salud", self._bucle_salud)):
            hilo = threading.Thread(target=objetivo, name=f"publicador-{nombre}", daemon=True)
            hilo.start()
            self._hilos.append(hilo)

    def detener(self) -> None:
        self.observacion.interrumpido()
        self._detener.set()
        for hilo in self._hilos:
            hilo.join(timeout=5)
        self._enviar_pendientes()  # último intento; lo que quede sigue en la cola
        self._latido()

    # --- eventos ------------------------------------------------------------------------------

    def _bucle_eventos(self) -> None:
        while not self._detener.is_set():
            enviados = self._enviar_pendientes()
            self._detener.wait(0.2 if enviados else 1.0)

    def _enviar_pendientes(self) -> int:
        enviados = 0
        for id_externo, cuerpo, intentos in self.cola.listos():
            inicio = time.monotonic()
            r = self.cliente.enviar_evento(cuerpo)
            if r.aceptado:
                self.latencia_ms = (time.monotonic() - inicio) * 1000
                self.cola.confirmar(id_externo)
                self.conectado = True
                enviados += 1
                duplicado = " (ya estaba registrado)" if (r.datos or {}).get("duplicado") else ""
                log.info("Evento %s publicado → %s%s", id_externo,
                         (r.datos or {}).get("veredicto"), duplicado)
            elif r.rechazo_definitivo:
                self.cola.rechazar(id_externo, f"{r.estado}: {r.datos}")
                log.error("El servidor rechazó %s por no cumplir el contrato: %s. Queda en la "
                          "tabla 'rechazados' de la cola.", id_externo, r.datos)
            else:
                espera = self.cola.reintentar_despues(id_externo, r.error)
                self.conectado = r.estado != 0
                if intentos == 0 or intentos % 10 == 0:
                    log.warning("No se pudo publicar %s (%s). Reintento en %.0f s; el evento "
                                "sigue en la cola local.", id_externo, r.error, espera)
                break  # mantener el orden: no saltar a los siguientes
        return enviados

    # --- salud y configuración ----------------------------------------------------------------

    def _bucle_salud(self) -> None:
        ultima_config = 0.0
        ultima_metrica = 0.0
        while not self._detener.is_set():
            self._latido()
            ahora = time.monotonic()
            if ahora - ultima_config >= self.intervalo_config_s:
                self._traer_configuracion()
                ultima_config = ahora
            if ahora - ultima_metrica >= 60:
                self._publicar_metricas()
                ultima_metrica = ahora
            self._detener.wait(self.intervalo_latido_s)

    def _latido(self) -> None:
        cerrados = self.cola.tramos()
        tramos = [t for _, t in cerrados]
        abierto = self.observacion.abierto()
        if abierto:
            tramos.append(abierto)
        estado = self.estado()
        r = self.cliente.enviar_latido({
            "box": self.box,
            "camara_conectada": bool(estado.get("camara_conectada")),
            "fps": estado.get("fps"),
            "zonas_alineadas": estado.get("zonas_alineadas"),
            "modelo": estado.get("modelo", ""),
            "cola_pendientes": self.cola.pendientes(),
            "tramos": tramos,
        })
        if r.aceptado:
            if not self.conectado:
                log.info("Conectado con el servidor %s", self.cliente.base)
            self.conectado = True
            self.cola.borrar_tramos([i for i, _ in cerrados])
        elif r.rechazo_definitivo:
            # Un tramo inválido no debe bloquear para siempre los latidos siguientes.
            log.error("El servidor rechazó el latido (%s): %s. Se descartan %s tramo(s) "
                      "guardado(s).", r.estado, r.error, len(cerrados))
            self.cola.borrar_tramos([i for i, _ in cerrados])
        else:
            if self.conectado:
                log.warning("Se perdió la conexión con el servidor: %s", r.error)
            self.conectado = False

    def _traer_configuracion(self) -> None:
        r = self.cliente.obtener_configuracion(self.box)
        if r.aceptado and r.datos:
            try:
                self.al_recibir_config(r.datos)
            except Exception:  # noqa: BLE001 - una configuración mala no tumba el servicio
                log.exception("No se pudo aplicar la configuración recibida")

    def _publicar_metricas(self) -> None:
        estado = self.estado()
        self.metricas.publicar({
            "fps": estado.get("fps") or 0.0,
            "camara_conectada": 1.0 if estado.get("camara_conectada") else 0.0,
            "cola_pendientes": float(self.cola.pendientes()),
            "latencia_ingesta_ms": self.latencia_ms or 0.0,
            "tiempo_activo_s": time.monotonic() - self._arranque,
        })

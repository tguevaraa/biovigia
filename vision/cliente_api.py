"""Adaptador del servidor (Adapter, Tabla 39): la canalización no conoce HTTP.

Solo viajan eventos confirmados, latidos de salud y, a pedido del operador, un fotograma
de referencia de la escena vacía. Todo dentro de la red interna (RNF-02).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import requests

log = logging.getLogger("vision.api")
TIEMPO_ESPERA = (5, 15)  # conexión, lectura


@dataclass
class Respuesta:
    estado: int               # 0 = sin conexión
    datos: Optional[dict]
    error: str = ""

    @property
    def aceptado(self) -> bool:
        return self.estado in (200, 201)

    @property
    def rechazo_definitivo(self) -> bool:
        """422: el cuerpo no cumple el contrato. Reintentar no lo arregla."""
        return self.estado in (400, 422)


class ClienteAPI:
    def __init__(self, servidor: str, token: str, verify: Any = True) -> None:
        self.base = servidor.rstrip("/") + "/api/v1"
        self.sesion = requests.Session()
        self.sesion.headers.update({"Authorization": f"Token {token}",
                                    "Accept": "application/json",
                                    "User-Agent": "biovigia-vision/0.1"})
        self.sesion.verify = verify

    def _pedir(self, metodo: str, ruta: str, **kwargs) -> Respuesta:
        try:
            r = self.sesion.request(metodo, self.base + ruta, timeout=TIEMPO_ESPERA, **kwargs)
        except requests.RequestException as exc:
            return Respuesta(0, None, f"sin conexión: {exc.__class__.__name__}")
        try:
            datos = r.json() if r.content else None
        except ValueError:
            datos = None
        error = ""
        if r.status_code >= 400:
            error = (datos or {}).get("detalle") or r.reason or f"HTTP {r.status_code}"
            if r.status_code == 401:
                error = "token inválido o ausente: revisa BIOVIGIA_TOKEN"
        return Respuesta(r.status_code, datos, error)

    def enviar_evento(self, payload: dict) -> Respuesta:
        return self._pedir("POST", "/eventos", json=payload)

    def enviar_latido(self, datos: dict) -> Respuesta:
        return self._pedir("POST", "/salud", json=datos)

    def obtener_configuracion(self, box: str) -> Respuesta:
        return self._pedir("GET", "/configuracion", params={"box": box})

    def enviar_referencia(self, box: str, jpeg_b64: str) -> Respuesta:
        return self._pedir("PUT", f"/boxes/{box}/referencia", json={"imagen_jpeg_b64": jpeg_b64})

"""Métricas de salud del borde (C5). Solo números: nunca imágenes, eventos ni personas.

Adapter con dos implementaciones: el registro local (por defecto) y Amazon CloudWatch,
que se activa con ``BIOVIGIA_CLOUDWATCH=1`` y requiere ``pip install boto3`` y
credenciales de AWS configuradas en el equipo.
"""
from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger("vision.metricas")


class Metricas(Protocol):
    def publicar(self, valores: dict[str, float]) -> None: ...


class MetricasRegistro:
    def publicar(self, valores: dict[str, float]) -> None:
        texto = ", ".join(f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}"
                          for k, v in valores.items())
        log.info("Salud: %s", texto)


class MetricasCloudWatch:
    ESPACIO = "BioVigIA/Borde"
    UNIDADES = {"fps": "Count/Second", "camara_conectada": "None", "cola_pendientes": "Count",
                "latencia_ingesta_ms": "Milliseconds", "tiempo_activo_s": "Seconds"}

    def __init__(self, box: str, region: str) -> None:
        import boto3  # noqa: PLC0415 - dependencia opcional

        self.box = box
        self.cliente = boto3.client("cloudwatch", region_name=region)

    def publicar(self, valores: dict[str, float]) -> None:
        datos = [{
            "MetricName": nombre,
            "Dimensions": [{"Name": "Box", "Value": self.box}],
            "Value": float(valor),
            "Unit": self.UNIDADES.get(nombre, "None"),
        } for nombre, valor in valores.items() if valor is not None]
        try:
            self.cliente.put_metric_data(Namespace=self.ESPACIO, MetricData=datos)
        except Exception as exc:  # noqa: BLE001 - sin internet se pierde la métrica, no el evento
            log.warning("CloudWatch no disponible: %s", exc)


def crear_metricas(usar_cloudwatch: bool, box: str, region: str) -> Metricas:
    if usar_cloudwatch:
        try:
            return MetricasCloudWatch(box, region)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo iniciar CloudWatch (%s); se usa el registro local.", exc)
    return MetricasRegistro()

"""Parámetros de operación y zonas de los recipientes (RF-01, RF-12, HU-01, HU-05)."""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from cuentas.models import AccionBitacora
from cuentas.servicios import registrar as registrar_bitacora

from ..models import Box, Parametros, Recipiente, TipoRecipiente, Zona
from .errores import CamaraInsuficiente, ErrorValidacion, NoEncontrado
from .ingesta import decodificar_evidencia
from .observacion import latido_vigente

ENTEROS = {"k_confirmacion", "n_confirmacion", "fps_muestreo", "retencion_dias"}
PUNTOS_MIN, PUNTOS_MAX = 3, 20
AREA_MINIMA = 0.0005  # fracción del fotograma; descarta polígonos degenerados


def obtener_box(codigo: str) -> Box:
    try:
        return Box.objects.get(codigo=codigo)
    except Box.DoesNotExist as exc:
        raise NoEncontrado(f"No existe el box «{codigo}».", campo="box") from exc


# --- Parámetros ------------------------------------------------------------------------------

def _convertir(campo: str, valor: Any) -> float | int:
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ErrorValidacion("debe ser un número", campo=campo) from exc
    if campo in ENTEROS:
        if not numero.is_integer():
            raise ErrorValidacion("debe ser un número entero", campo=campo)
        return int(numero)
    return round(numero, 3)


@transaction.atomic
def actualizar_parametros(datos: dict[str, Any], usuario, request=None) -> Parametros:
    """Valida todo antes de guardar: si un valor está fuera de rango no cambia ninguno."""
    actual = Parametros.actual()
    nuevos = actual.como_dict()
    for campo, valor in datos.items():
        if campo not in Parametros.RANGOS:
            continue
        numero = _convertir(campo, valor)
        minimo, maximo = Parametros.RANGOS[campo]
        if not minimo <= numero <= maximo:
            raise ErrorValidacion(f"debe estar entre {minimo} y {maximo}", campo=campo)
        nuevos[campo] = numero
    if nuevos["k_confirmacion"] > nuevos["n_confirmacion"]:
        raise ErrorValidacion("k no puede ser mayor que N en la regla k-de-N",
                              campo="k_confirmacion")
    cambios = [f"{c}: {getattr(actual, c)} → {v}" for c, v in nuevos.items()
               if getattr(actual, c) != v]
    for campo, valor in nuevos.items():
        setattr(actual, campo, valor)
    actual.actualizado_por = usuario
    actual.save()
    if cambios:
        registrar_bitacora(request, AccionBitacora.CONFIGURACION,
                           "Parámetros: " + "; ".join(cambios), usuario)
    return actual


def limites() -> dict[str, dict[str, float]]:
    return {c: {"min": r[0], "max": r[1]} for c, r in Parametros.RANGOS.items()}


# --- Zonas -----------------------------------------------------------------------------------

def _area(puntos: list[list[float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(puntos, puntos[1:] + puntos[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def validar_puntos(puntos: Any) -> list[list[float]]:
    if not isinstance(puntos, list) or not PUNTOS_MIN <= len(puntos) <= PUNTOS_MAX:
        raise ErrorValidacion(f"el polígono necesita entre {PUNTOS_MIN} y {PUNTOS_MAX} puntos",
                              campo="puntos")
    limpios = []
    for p in puntos:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise ErrorValidacion("cada punto es [x, y]", campo="puntos")
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError) as exc:
            raise ErrorValidacion("las coordenadas deben ser números", campo="puntos") from exc
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ErrorValidacion("las coordenadas van normalizadas entre 0 y 1", campo="puntos")
        limpios.append([round(x, 4), round(y, 4)])
    if _area(limpios) < AREA_MINIMA:
        raise ErrorValidacion("el polígono es demasiado pequeño o sus puntos están alineados",
                              campo="puntos")
    return limpios


def zonas_de(box: Box) -> dict[str, dict[str, Any] | None]:
    resultado: dict[str, dict[str, Any] | None] = {t: None for t in TipoRecipiente.values}
    for zona in Zona.objects.select_related("recipiente", "actualizado_por").filter(
            recipiente__box=box):
        resultado[zona.recipiente.tipo] = {
            "puntos": zona.puntos,
            "actualizado_en": timezone.localtime(zona.actualizado_en).isoformat(
                timespec="seconds"),
            "actualizado_por": (zona.actualizado_por.nombre_visible
                                if zona.actualizado_por else None),
        }
    return resultado


def estado_camara(box: Box) -> dict[str, Any]:
    minimo = settings.BIOVIGIA_FPS_MINIMO
    conectado = latido_vigente(box)
    fps = box.fps_medido if conectado else None
    return {
        "conectada": conectado and box.camara_conectada,
        "fps": round(fps, 1) if fps is not None else None,
        "fps_minimo": minimo,
        "cumple": bool(conectado and box.camara_conectada and fps is not None and fps >= minimo),
        "referencia_disponible": bool(box.referencia),
        "referencia_en": (timezone.localtime(box.referencia_en).isoformat(timespec="seconds")
                          if box.referencia_en else None),
    }


@transaction.atomic
def guardar_zonas(box: Box, zonas: list[dict[str, Any]], usuario, request=None) -> Box:
    """Reemplaza solo los polígonos enviados; el otro recipiente no cambia (HU-01, crit. 2)."""
    if not isinstance(zonas, list) or not zonas:
        raise ErrorValidacion("envía al menos una zona", campo="zonas")
    camara = estado_camara(box)
    if not camara["cumple"]:
        fps = camara["fps"]
        detalle = ("La cámara no está enviando fotogramas en este momento"
                   if fps is None else f"La cámara entrega {fps} fps")
        raise CamaraInsuficiente(f"{detalle}; se necesitan al menos {camara['fps_minimo']} fps "
                                 "para guardar zonas.")
    for item in zonas:
        tipo = item.get("tipo") if isinstance(item, dict) else None
        if tipo not in TipoRecipiente.values:
            raise ErrorValidacion("tipo debe ser rojo o comun", campo="tipo")
        puntos = validar_puntos(item.get("puntos"))
        recipiente, _ = Recipiente.objects.get_or_create(box=box, tipo=tipo)
        Zona.objects.update_or_create(
            recipiente=recipiente, defaults={"puntos": puntos, "actualizado_por": usuario})
    registrar_bitacora(request, AccionBitacora.CONFIGURACION,
                       f"Zonas de {box.codigo}: {', '.join(z['tipo'] for z in zonas)}", usuario)
    return box


def guardar_referencia(box: Box, jpeg_b64: str) -> Box:
    """Fotograma de la escena vacía, enviado por el servicio de visión para trazar zonas."""
    crudo = decodificar_evidencia(jpeg_b64)
    if box.referencia:
        box.referencia.delete(save=False)
    box.referencia.save(f"{box.codigo}.jpg", ContentFile(crudo), save=False)
    box.referencia_en = timezone.now()
    box.save(update_fields=["referencia", "referencia_en"])
    return box


def configuracion_para_vision(box: Box) -> dict[str, Any]:
    """Lo que el servicio de visión necesita para operar (RNF-16: sin redesplegar)."""
    p = Parametros.actual()
    return {
        "box": box.codigo,
        "parametros": p.como_dict(),
        "zonas": {t: (z["puntos"] if z else None) for t, z in zonas_de(box).items()},
        "actualizado_en": timezone.localtime().isoformat(timespec="seconds"),
    }

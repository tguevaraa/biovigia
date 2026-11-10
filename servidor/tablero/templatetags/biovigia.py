"""Filtros de presentación en el lenguaje del laboratorio (RNF-23)."""
from django import template
from django.utils import timezone

register = template.Library()

RECIPIENTE = {"rojo": "Rojo (infeccioso)", "comun": "Común"}
ESTADO = {"normal": "Normal", "contaminado": "Contaminado"}


@register.filter
def recipiente(tipo: str) -> str:
    return RECIPIENTE.get(tipo, tipo)


@register.filter
def estado(valor: str) -> str:
    return ESTADO.get(valor, valor)


@register.filter
def porcentaje(valor, decimales: int = 1) -> str:
    if valor is None or valor == "":
        return "—"
    return f"{float(valor) * 100:.{int(decimales)}f} %".replace(".", ",")


@register.filter
def confianza(valor) -> str:
    if valor is None:
        return "—"
    return f"{float(valor) * 100:.0f} %"


@register.filter
def altura(valor, maximo) -> int:
    """Altura de una barra en porcentaje del máximo (0 si no hay valor)."""
    try:
        return max(2, round(float(valor) * 100 / float(maximo))) if valor else 0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.filter
def nivel(valor, maximo) -> int:
    """Nivel 0-4 de la escala secuencial de un solo tono del mapa de calor."""
    if not valor or not maximo:
        return 0
    return min(4, max(1, round(float(valor) * 4 / float(maximo))))


@register.filter
def duracion(minutos) -> str:
    minutos = int(minutos or 0)
    if minutos < 60:
        return f"{minutos} min"
    return f"{minutos // 60} h {minutos % 60:02d}"


@register.filter
def local(valor):
    return timezone.localtime(valor) if valor else valor


@register.simple_tag
def turno_texto(codigo: str) -> str:
    from vigilancia.servicios.tiempo import etiqueta_turno

    return etiqueta_turno(codigo)

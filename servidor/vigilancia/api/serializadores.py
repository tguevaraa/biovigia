"""Serializadores: validan la forma de las peticiones y dan forma a las respuestas.

La validación de reglas de negocio vive en ``vigilancia.servicios``; aquí solo se comprueba
que cada campo tenga el tipo y el rango que pide el contrato.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from ..models import Evento, TipoRecipiente, Veredicto
from ..servicios.eventos import estado_recipiente_tras
from ..servicios.tiempo import etiqueta_turno


class FechaConZona(serializers.Field):
    """ISO 8601 con zona horaria obligatoria (contrato v1, regla 3)."""

    default_error_messages = {
        "formato": "debe ser ISO 8601, por ejemplo 2026-10-27T10:42:18.331-05:00",
        "zona": "debe incluir la zona horaria (por ejemplo -05:00)",
    }

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("formato")
        try:
            valor = parse_datetime(data.strip())
        except ValueError:
            valor = None
        if valor is None:
            self.fail("formato")
        if valor.tzinfo is None:
            self.fail("zona")
        return valor

    def to_representation(self, value):
        return timezone.localtime(value).isoformat(timespec="seconds")


class EventoEntradaSerializer(serializers.Serializer):
    id_externo = serializers.CharField(max_length=80)
    box = serializers.CharField(max_length=20)
    recipiente = serializers.ChoiceField(choices=TipoRecipiente.values)
    veredicto = serializers.ChoiceField(choices=Veredicto.values)
    confianza = serializers.FloatField(
        min_value=0, max_value=1,
        error_messages={"min_value": "debe estar entre 0 y 1",
                        "max_value": "debe estar entre 0 y 1"})
    ocurrido_en = FechaConZona()
    modelo = serializers.CharField(max_length=40)
    rasgos = serializers.DictField()
    evidencia_jpeg_b64 = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, trim_whitespace=True,
        max_length=3 * 1024 * 1024)


class TramoSerializer(serializers.Serializer):
    inicio = FechaConZona()
    fin = FechaConZona()

    def validate(self, attrs):
        if attrs["fin"] < attrs["inicio"]:
            raise serializers.ValidationError({"fin": "no puede ser anterior a inicio"})
        if attrs["fin"] > timezone.now() + timedelta(seconds=30):
            raise serializers.ValidationError({"fin": "no puede ser una fecha futura"})
        return attrs


class SaludSerializer(serializers.Serializer):
    box = serializers.CharField(max_length=20)
    camara_conectada = serializers.BooleanField()
    fps = serializers.FloatField(min_value=0, max_value=240, allow_null=True, required=False)
    zonas_alineadas = serializers.BooleanField(allow_null=True, required=False)
    modelo = serializers.CharField(max_length=40, allow_blank=True, required=False)
    cola_pendientes = serializers.IntegerField(min_value=0, required=False)
    tramos = TramoSerializer(many=True, required=False)


class ReferenciaSerializer(serializers.Serializer):
    imagen_jpeg_b64 = serializers.CharField(max_length=3 * 1024 * 1024)


class ZonaEntradaSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=TipoRecipiente.values)
    puntos = serializers.ListField(child=serializers.ListField(
        child=serializers.FloatField(), min_length=2, max_length=2))


class ZonasEntradaSerializer(serializers.Serializer):
    zonas = ZonaEntradaSerializer(many=True)


class RecambioEntradaSerializer(serializers.Serializer):
    box = serializers.CharField(max_length=20)
    tipo = serializers.ChoiceField(choices=TipoRecipiente.values)


class AccionEntradaSerializer(serializers.Serializer):
    descripcion = serializers.CharField(max_length=1000)
    responsable = serializers.CharField(max_length=120, required=False, allow_blank=True)
    eventos = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


# --- Salidas ------------------------------------------------------------------------------

def evidencia_de(evento: Evento) -> dict:
    if evento.evidencia_disponible:
        return {"disponible": True, "url": f"/api/v1/eventos/{evento.pk}/evidencia"}
    if evento.evidencia_eliminada_en:
        return {"disponible": False, "motivo": "retencion"}
    return {"disponible": False, "motivo": "sin_evidencia"}


def evento_resumen(evento: Evento) -> dict:
    return {
        "id": evento.pk,
        "codigo": evento.codigo,
        "ocurrido_en": timezone.localtime(evento.ocurrido_en).isoformat(timespec="seconds"),
        "turno": evento.turno,
        "turno_etiqueta": etiqueta_turno(evento.turno),
        "box": evento.recipiente.box.codigo,
        "recipiente": evento.recipiente.tipo,
        "veredicto": evento.veredicto,
        "confianza": float(evento.confianza),
        "evidencia": evidencia_de(evento),
    }


def evento_detalle(evento: Evento) -> dict:
    datos = evento_resumen(evento)
    datos.update({
        "modelo": evento.modelo,
        "rasgos": evento.rasgos,
        "estado_recipiente_tras_evento": estado_recipiente_tras(evento),
        "acciones": [
            {"id": a.pk, "descripcion": a.descripcion, "responsable": a.responsable,
             "registrada_en": timezone.localtime(a.registrada_en).isoformat(timespec="seconds")}
            for a in evento.acciones.all()
        ],
    })
    return datos


def usuario_salida(usuario) -> dict:
    return {
        "id": usuario.pk,
        "username": usuario.username,
        "nombre": usuario.nombre_visible,
        "first_name": usuario.first_name,
        "last_name": usuario.last_name,
        "email": usuario.email,
        "rol": usuario.rol,
        "activo": usuario.is_active,
        "ultimo_acceso": (timezone.localtime(usuario.last_login).isoformat(timespec="seconds")
                          if usuario.last_login else None),
    }

"""Modelo de datos de BioVigIA (componentes C3 y C3b).

Las cinco tablas del contrato v1 (recipiente, evento, recambio, cambio_estado y el usuario)
más las fuentes que agregó la sección 8.5 del informe: tramos observados (para el periodo
no observado), acciones correctivas, zonas y parámetros. Ninguna tabla guarda datos que
identifiquen a pacientes o a trabajadores observados (RNF-05).
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TipoRecipiente(models.TextChoices):
    ROJO = "rojo", "Rojo (infeccioso)"
    COMUN = "comun", "Común"


class EstadoRecipiente(models.TextChoices):
    NORMAL = "normal", "Normal"
    CONTAMINADO = "contaminado", "Contaminado"


class Veredicto(models.TextChoices):
    CONFORME = "conforme", "Conforme"
    NO_CONFORME = "no_conforme", "No conforme"


VEREDICTO_POR_TIPO = {
    TipoRecipiente.ROJO: Veredicto.CONFORME,
    TipoRecipiente.COMUN: Veredicto.NO_CONFORME,
}


class Box(models.Model):
    """Puesto de descarte observado por una cámara (un dispositivo de borde)."""

    codigo = models.CharField(max_length=20, unique=True, help_text="Ej.: box-2")
    nombre = models.CharField(max_length=60, blank=True)
    activo = models.BooleanField(default=True)
    # Último latido del servicio de visión y lo que informó.
    ultimo_latido = models.DateTimeField(null=True, blank=True)
    fps_medido = models.FloatField(null=True, blank=True)
    camara_conectada = models.BooleanField(default=False)
    zonas_alineadas = models.BooleanField(null=True, blank=True)
    modelo_en_uso = models.CharField(max_length=40, blank=True)
    cola_pendientes = models.PositiveIntegerField(default=0)
    # Fotograma de referencia de la escena vacía, solo para trazar zonas (PAN-09).
    referencia = models.FileField(upload_to="referencia/", blank=True)
    referencia_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "box"
        verbose_name_plural = "boxes"
        ordering = ["codigo"]

    def __str__(self) -> str:
        return self.etiqueta

    @property
    def etiqueta(self) -> str:
        if self.nombre:
            return self.nombre
        return self.codigo.replace("-", " ").capitalize()


class Recipiente(models.Model):
    box = models.ForeignKey(Box, on_delete=models.CASCADE, related_name="recipientes")
    tipo = models.CharField(max_length=6, choices=TipoRecipiente.choices)
    estado = models.CharField(
        max_length=12, choices=EstadoRecipiente.choices, default=EstadoRecipiente.NORMAL
    )
    contaminado_desde = models.DateTimeField(null=True, blank=True)
    evento_causa = models.ForeignKey(
        "Evento", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "recipiente"
        verbose_name_plural = "recipientes"
        ordering = ["box__codigo", "-tipo"]  # rojo antes que común
        constraints = [
            models.UniqueConstraint(fields=["box", "tipo"], name="recipiente_unico_por_box"),
        ]

    def __str__(self) -> str:
        return f"{self.box.etiqueta} · {self.get_tipo_display()}"

    @property
    def contaminado(self) -> bool:
        return self.estado == EstadoRecipiente.CONTAMINADO


class Evento(models.Model):
    """Un descarte confirmado por el servicio de visión."""

    id_externo = models.CharField(max_length=80, unique=True)
    recipiente = models.ForeignKey(Recipiente, on_delete=models.PROTECT, related_name="eventos")
    veredicto = models.CharField(max_length=12, choices=Veredicto.choices)
    # Lo que envió la visión, para auditar discrepancias (contrato v1, regla 1).
    veredicto_reportado = models.CharField(max_length=12, choices=Veredicto.choices)
    confianza = models.DecimalField(
        max_digits=4, decimal_places=3,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    ocurrido_en = models.DateTimeField(db_index=True)
    recibido_en = models.DateTimeField(auto_now_add=True)
    turno = models.CharField(max_length=16, db_index=True)
    modelo = models.CharField(max_length=40)
    rasgos = models.JSONField(default=dict, blank=True)
    evidencia = models.FileField(upload_to="evidencia/%Y/%m/", blank=True)
    evidencia_eliminada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "evento de descarte"
        verbose_name_plural = "eventos de descarte"
        ordering = ["-ocurrido_en", "-id"]
        indexes = [models.Index(fields=["veredicto", "ocurrido_en"])]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.get_veredicto_display()}"

    @property
    def codigo(self) -> str:
        return f"EV-{self.pk:04d}" if self.pk else "EV-nuevo"

    @property
    def conforme(self) -> bool:
        return self.veredicto == Veredicto.CONFORME

    @property
    def evidencia_disponible(self) -> bool:
        return bool(self.evidencia) and self.evidencia_eliminada_en is None


class Recambio(models.Model):
    recipiente = models.ForeignKey(Recipiente, on_delete=models.PROTECT, related_name="recambios")
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recambios"
    )
    registrado_en = models.DateTimeField(default=timezone.now)
    evento_causa = models.ForeignKey(
        Evento, null=True, blank=True, on_delete=models.SET_NULL, related_name="recambios"
    )

    class Meta:
        verbose_name = "recambio"
        verbose_name_plural = "recambios"
        ordering = ["-registrado_en"]

    def __str__(self) -> str:
        return f"Recambio {self.pk} · {self.recipiente}"


class CambioEstado(models.Model):
    """Historial de cada transición normal ↔ contaminado (RF-05)."""

    recipiente = models.ForeignKey(Recipiente, on_delete=models.CASCADE, related_name="cambios")
    estado_anterior = models.CharField(max_length=12, choices=EstadoRecipiente.choices)
    estado_nuevo = models.CharField(max_length=12, choices=EstadoRecipiente.choices)
    ocurrido_en = models.DateTimeField(db_index=True)
    evento = models.ForeignKey(Evento, null=True, blank=True, on_delete=models.SET_NULL)
    recambio = models.ForeignKey(Recambio, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "cambio de estado"
        verbose_name_plural = "cambios de estado"
        ordering = ["-ocurrido_en", "-id"]


class TramoObservado(models.Model):
    """Intervalo en el que la cámara estuvo observando de verdad.

    Lo que no está cubierto por un tramo es periodo no observado (RNF-06). Se guarda lo
    observado, y no las desconexiones, porque así una caída total del borde —que no puede
    avisar de nada— también queda registrada como hueco.
    """

    box = models.ForeignKey(Box, on_delete=models.CASCADE, related_name="tramos")
    inicio = models.DateTimeField(db_index=True)
    fin = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "tramo observado"
        verbose_name_plural = "tramos observados"
        ordering = ["box", "inicio"]


class AccionCorrectiva(models.Model):
    """Nota del responsable de bioseguridad asociada a uno o varios eventos (RF-10)."""

    descripcion = models.TextField(max_length=1000)
    responsable = models.CharField(
        max_length=120, blank=True,
        help_text="Área o cargo encargado de ejecutar la acción (no una persona observada).",
    )
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="acciones"
    )
    registrada_en = models.DateTimeField(auto_now_add=True)
    eventos = models.ManyToManyField(Evento, related_name="acciones")

    class Meta:
        verbose_name = "acción correctiva"
        verbose_name_plural = "acciones correctivas"
        ordering = ["-registrada_en"]

    def __str__(self) -> str:
        return self.descripcion[:60]


class Zona(models.Model):
    """Polígono de la boca de un recipiente sobre el fotograma normalizado (RF-01).

    Los puntos se guardan normalizados entre 0 y 1, así el polígono no depende de la
    resolución de la cámara.
    """

    recipiente = models.OneToOneField(Recipiente, on_delete=models.CASCADE, related_name="zona")
    puntos = models.JSONField(help_text="Lista de [x, y] normalizados entre 0 y 1.")
    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "zona"
        verbose_name_plural = "zonas"


class Parametros(models.Model):
    """Parámetros de operación (RF-12). Una sola fila; se accede con ``Parametros.actual()``."""

    # (mínimo, máximo) admitidos. Fuera de rango, el cambio se rechaza (HU-05, criterio 3).
    RANGOS = {
        "umbral_confianza": (0.10, 0.95),
        "ventana_confirmacion_s": (0.5, 5.0),
        "k_confirmacion": (1, 15),
        "n_confirmacion": (1, 30),
        "fps_muestreo": (15, 30),          # Tabla 45, inconsistencia 5
        "retencion_dias": (7, 90),         # RNF-17 y Tabla 45, inconsistencia 6
    }

    umbral_confianza = models.FloatField(default=0.50)
    ventana_confirmacion_s = models.FloatField(default=1.5)
    k_confirmacion = models.PositiveSmallIntegerField(default=3)
    n_confirmacion = models.PositiveSmallIntegerField(default=5)
    fps_muestreo = models.PositiveSmallIntegerField(default=15)
    retencion_dias = models.PositiveSmallIntegerField(default=30)
    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "parámetros de operación"
        verbose_name_plural = "parámetros de operación"

    def save(self, *args, **kwargs):
        self.pk = 1  # fila única
        super().save(*args, **kwargs)

    @classmethod
    def actual(cls) -> "Parametros":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def como_dict(self) -> dict:
        return {campo: getattr(self, campo) for campo in self.RANGOS}

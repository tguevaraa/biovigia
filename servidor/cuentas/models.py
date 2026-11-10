"""Usuarios, roles y bitácora de auditoría (M6, RF-11, RNF-13, RNF-14)."""
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied
from django.db import models


class Rol(models.TextChoices):
    """Roles del sistema. El rol lo decide siempre el servidor (contrato v1, regla 6)."""

    ADMIN = "admin", "Administrador"
    SUPERVISOR = "supervisor", "Responsable de bioseguridad"
    OPERATIVO = "operativo", "Personal de limpieza"
    # Cuenta técnica del servicio de visión: se autentica con token y no entra a pantallas.
    SERVICIO = "servicio", "Servicio de visión"


ROLES_HUMANOS = (Rol.ADMIN, Rol.SUPERVISOR, Rol.OPERATIVO)


class Usuario(AbstractUser):
    """Usuario de Django con el rol de BioVigIA. Sin cuentas compartidas (RNF-13)."""

    rol = models.CharField(max_length=12, choices=Rol.choices, default=Rol.OPERATIVO)

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["username"]

    def save(self, *args, **kwargs):
        # Un superusuario creado con createsuperuser es, a efectos del sistema, administrador.
        if self.is_superuser and self.rol != Rol.ADMIN:
            self.rol = Rol.ADMIN
        super().save(*args, **kwargs)

    @property
    def nombre_visible(self) -> str:
        return self.get_full_name() or self.username

    @property
    def iniciales(self) -> str:
        partes = [p for p in (self.first_name, self.last_name) if p]
        if partes:
            return "".join(p[0] for p in partes).upper()[:2]
        return self.username[:2].upper()

    def tiene_rol(self, *roles: str) -> bool:
        return self.is_active and self.rol in roles

    @property
    def es_humano(self) -> bool:
        return self.rol in ROLES_HUMANOS


class AccionBitacora(models.TextChoices):
    INICIO_SESION = "inicio_sesion", "Inicio de sesión"
    INICIO_FALLIDO = "inicio_fallido", "Inicio de sesión fallido"
    CIERRE_SESION = "cierre_sesion", "Cierre de sesión"
    VER_EVIDENCIA = "ver_evidencia", "Consulta de evidencia"
    EXPORTAR = "exportar", "Exportación de reporte"
    RECAMBIO = "recambio", "Registro de recambio"
    ACCION_CORRECTIVA = "accion_correctiva", "Registro de acción correctiva"
    CONFIGURACION = "configuracion", "Cambio de configuración"
    USUARIOS = "usuarios", "Gestión de usuarios"
    ACCESO_DENEGADO = "acceso_denegado", "Acceso no autorizado"


class Bitacora(models.Model):
    """Registro de auditoría de solo inserción: no se edita ni se borra desde la aplicación."""

    ocurrido_en = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        Usuario, null=True, blank=True, on_delete=models.SET_NULL, related_name="bitacora"
    )
    # Se guarda también el nombre por si la cuenta se desactiva o se renombra después.
    usuario_nombre = models.CharField(max_length=150, blank=True)
    accion = models.CharField(max_length=24, choices=AccionBitacora.choices)
    detalle = models.CharField(max_length=500, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "entrada de bitácora"
        verbose_name_plural = "bitácora"
        ordering = ["-ocurrido_en"]

    def __str__(self) -> str:
        return f"{self.ocurrido_en:%Y-%m-%d %H:%M} · {self.usuario_nombre} · {self.accion}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("La bitácora no se puede modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("La bitácora no se puede borrar.")

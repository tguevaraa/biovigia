"""Servicios de la capa de dominio para cuentas: bitácora y gestión de usuarios."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ROLES_HUMANOS, AccionBitacora, Bitacora, Rol, Usuario

PANTALLA_INICIAL = {
    Rol.ADMIN: "tablero:principal",
    Rol.SUPERVISOR: "tablero:principal",
    Rol.OPERATIVO: "tablero:recipientes",
}


class ErrorGestionUsuarios(Exception):
    """Regla de negocio incumplida al crear o editar una cuenta."""

    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(detalle)
        self.campo = campo
        self.detalle = detalle


def ip_de(request) -> str | None:
    if request is None:
        return None
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR")
    if reenviada:
        return reenviada.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def registrar(request, accion: str, detalle: str = "", usuario: Usuario | None = None) -> None:
    """Escribe una línea en la bitácora. Nunca lanza: la auditoría no tumba la petición."""
    if usuario is None and request is not None:
        candidato = getattr(request, "user", None)
        usuario = candidato if getattr(candidato, "is_authenticated", False) else None
    try:
        Bitacora.objects.create(
            usuario=usuario,
            usuario_nombre=usuario.username if usuario else "",
            accion=accion,
            detalle=detalle[:500],
            ip=ip_de(request),
        )
    except Exception:  # pragma: no cover - defensivo
        import logging

        logging.getLogger("biovigia").exception("No se pudo escribir en la bitácora")


def pantalla_inicial(usuario: Usuario) -> str:
    """Nombre de la ruta a la que se envía al usuario tras iniciar sesión (Tabla 32)."""
    return PANTALLA_INICIAL.get(usuario.rol, "tablero:mi_cuenta")


def _validar_rol(rol: str) -> str:
    if rol not in ROLES_HUMANOS:
        raise ErrorGestionUsuarios("rol", "Rol no válido: use admin, supervisor u operativo.")
    return rol


@transaction.atomic
def crear_usuario(datos: dict[str, Any], autor: Usuario, request=None) -> Usuario:
    username = (datos.get("username") or "").strip()
    if not username:
        raise ErrorGestionUsuarios("username", "El nombre de usuario es obligatorio.")
    if Usuario.objects.filter(username__iexact=username).exists():
        raise ErrorGestionUsuarios("username", "Ya existe una cuenta con ese nombre de usuario.")
    rol = _validar_rol(datos.get("rol", ""))
    password = datos.get("password") or ""
    usuario = Usuario(
        username=username,
        first_name=(datos.get("first_name") or "").strip(),
        last_name=(datos.get("last_name") or "").strip(),
        email=(datos.get("email") or "").strip(),
        rol=rol,
        is_staff=False,
    )
    try:
        validate_password(password, user=usuario)
    except ValidationError as exc:
        raise ErrorGestionUsuarios("password", " ".join(exc.messages)) from exc
    usuario.set_password(password)
    usuario.save()
    registrar(request, AccionBitacora.USUARIOS, f"Creó la cuenta {username} con rol {rol}", autor)
    return usuario


@transaction.atomic
def actualizar_usuario(usuario: Usuario, datos: dict[str, Any], autor: Usuario,
                       request=None) -> Usuario:
    if usuario.rol == Rol.SERVICIO:
        raise ErrorGestionUsuarios("rol", "Las cuentas del servicio de visión se gestionan "
                                          "desde el panel técnico.")
    cambios = []
    for campo in ("first_name", "last_name", "email"):
        if campo in datos:
            setattr(usuario, campo, (datos[campo] or "").strip())
            cambios.append(campo)
    if "rol" in datos:
        nuevo = _validar_rol(datos["rol"])
        if usuario.pk == autor.pk and nuevo != Rol.ADMIN:
            raise ErrorGestionUsuarios("rol", "No puedes quitarte a ti mismo el rol de "
                                              "administrador.")
        if usuario.is_superuser and nuevo != Rol.ADMIN:
            raise ErrorGestionUsuarios("rol", "Un superusuario siempre es administrador.")
        usuario.rol = nuevo
        cambios.append(f"rol={nuevo}")
    if "is_active" in datos:
        activo = bool(datos["is_active"])
        if usuario.pk == autor.pk and not activo:
            raise ErrorGestionUsuarios("is_active", "No puedes desactivar tu propia cuenta.")
        usuario.is_active = activo
        cambios.append("activo" if activo else "desactivado")
    if datos.get("password"):
        try:
            validate_password(datos["password"], user=usuario)
        except ValidationError as exc:
            raise ErrorGestionUsuarios("password", " ".join(exc.messages)) from exc
        usuario.set_password(datos["password"])
        cambios.append("contraseña")
    usuario.save()
    registrar(request, AccionBitacora.USUARIOS,
              f"Editó la cuenta {usuario.username}: {', '.join(cambios) or 'sin cambios'}", autor)
    return usuario

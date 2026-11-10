"""Control de acceso por rol, en un solo lugar para la API y para las pantallas (RNF-13)."""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Rol

# Matriz de accesos (Tabla 32 del informe). Clave = recurso, valor = roles permitidos.
ACCESOS = {
    "tablero": (Rol.ADMIN, Rol.SUPERVISOR),
    "eventos": (Rol.ADMIN, Rol.SUPERVISOR),
    "evidencia": (Rol.ADMIN, Rol.SUPERVISOR),
    "recipientes": (Rol.ADMIN, Rol.SUPERVISOR, Rol.OPERATIVO),
    "recambio": (Rol.ADMIN, Rol.OPERATIVO),
    "reportes": (Rol.ADMIN, Rol.SUPERVISOR),
    "acciones": (Rol.ADMIN, Rol.SUPERVISOR),
    "zonas": (Rol.ADMIN,),
    "parametros": (Rol.ADMIN,),
    "usuarios": (Rol.ADMIN,),
    "cuenta": (Rol.ADMIN, Rol.SUPERVISOR, Rol.OPERATIVO),
    "ingesta": (Rol.SERVICIO,),
}


def puede(usuario, recurso: str) -> bool:
    if not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return False
    return usuario.rol in ACCESOS[recurso]


def requiere_acceso(recurso: str):
    """Decorador para vistas de plantilla: sin sesión → login; sin rol → aviso 403."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not puede(request.user, recurso):
                raise PermissionDenied(recurso)
            return vista(request, *args, **kwargs)

        envoltura.recurso = recurso
        return envoltura

    return decorador


class AccesoPorRol(BasePermission):
    """Permiso DRF. La vista declara ``recurso = "<clave>"`` o ``recursos = {"GET": ...}``."""

    message = "Tu rol no tiene acceso a este recurso."

    def has_permission(self, request, view) -> bool:
        recurso = getattr(view, "recursos", {}).get(request.method) or getattr(
            view, "recurso", None)
        if recurso is None:  # pragma: no cover - error de programación
            raise RuntimeError(f"La vista {view.__class__.__name__} no declara 'recurso'.")
        return puede(request.user, recurso)

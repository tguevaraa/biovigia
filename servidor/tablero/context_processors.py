"""Barra de navegación según el rol: solo se muestran los enlaces que el rol puede abrir.

Ocultar enlaces es comodidad, no seguridad: cada vista vuelve a comprobar el rol.
"""
from cuentas.permisos import puede

MENU = [
    ("principal", "Tablero principal", "tablero:principal", "tablero"),
    ("eventos", "Eventos", "tablero:eventos", "eventos"),
    ("recipientes", "Estado de recipientes", "tablero:recipientes", "recipientes"),
    ("reportes", "Reportes e indicadores", "tablero:reportes", "reportes"),
    ("acciones", "Acciones correctivas", "tablero:acciones", "acciones"),
    ("config", "Configuración", "tablero:zonas", "zonas"),
]


def navegacion(request):
    usuario = getattr(request, "user", None)
    if not usuario or not usuario.is_authenticated:
        return {"menu": []}
    return {
        "menu": [
            {"clave": clave, "texto": texto, "ruta": ruta}
            for clave, texto, ruta, recurso in MENU if puede(usuario, recurso)
        ],
    }

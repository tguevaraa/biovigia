"""Rutas de la API v1. Sin barra final, como en el contrato (``/api/v1/eventos``)."""
from django.urls import path

from . import vistas as v

app_name = "api"

urlpatterns = [
    path("auth/login", v.LoginVista.as_view(), name="login"),
    path("auth/logout", v.LogoutVista.as_view(), name="logout"),
    path("auth/me", v.YoVista.as_view(), name="me"),
    path("eventos", v.EventosVista.as_view(), name="eventos"),
    path("eventos/<int:evento_id>", v.EventoDetalleVista.as_view(), name="evento"),
    path("eventos/<int:evento_id>/evidencia", v.EventoEvidenciaVista.as_view(),
         name="evidencia"),
    path("tablero", v.TableroVista.as_view(), name="tablero"),
    path("recipientes", v.RecipientesVista.as_view(), name="recipientes"),
    path("recambios", v.RecambiosVista.as_view(), name="recambios"),
    path("reportes", v.ReportesVista.as_view(), name="reportes"),
    path("reportes/exportar", v.ReportesExportarVista.as_view(), name="exportar"),
    path("acciones", v.AccionesVista.as_view(), name="acciones"),
    path("boxes/<str:box>/zonas", v.ZonasVista.as_view(), name="zonas"),
    path("boxes/<str:box>/referencia", v.ReferenciaVista.as_view(), name="referencia"),
    path("parametros", v.ParametrosVista.as_view(), name="parametros"),
    path("usuarios", v.UsuariosVista.as_view(), name="usuarios"),
    path("usuarios/<int:usuario_id>", v.UsuarioDetalleVista.as_view(), name="usuario"),
    path("salud", v.SaludVista.as_view(), name="salud"),
    path("configuracion", v.ConfiguracionVisionVista.as_view(), name="configuracion"),
]

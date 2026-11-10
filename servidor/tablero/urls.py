from django.urls import path

from . import views

app_name = "tablero"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("ingresar/", views.login_vista, name="login"),                        # PAN-01
    path("salir/", views.logout_vista, name="logout"),
    path("tablero/", views.principal, name="principal"),                       # PAN-02
    path("eventos/", views.lista_eventos, name="eventos"),                     # PAN-03
    path("eventos/<int:evento_id>/", views.evento_detalle, name="evento"),     # PAN-04
    path("eventos/<int:evento_id>/evidencia.jpg", views.evidencia, name="evidencia"),
    path("recipientes/", views.estado_recipientes, name="recipientes"),        # PAN-05
    path("recipientes/<str:box>/<str:tipo>/recambio/", views.registrar_recambio,
         name="recambio"),                                                     # PAN-06
    path("reportes/", views.vista_reportes, name="reportes"),                  # PAN-07
    path("reportes/exportar/", views.exportar, name="exportar"),
    path("acciones/", views.vista_acciones, name="acciones"),                  # PAN-08
    path("configuracion/zonas/", views.zonas, name="zonas"),                   # PAN-09
    path("configuracion/parametros/", views.parametros, name="parametros"),    # PAN-10
    path("configuracion/usuarios/", views.usuarios, name="usuarios"),          # PAN-11
    path("configuracion/usuarios/<int:usuario_id>/", views.usuario_editar,
         name="usuario_editar"),
    path("mi-cuenta/", views.mi_cuenta, name="mi_cuenta"),                     # PAN-12
]

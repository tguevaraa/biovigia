"""Rutas raíz: panel de Django, API v1 y pantallas del tablero."""
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "BioVigIA · Administración técnica"
admin.site.site_title = "BioVigIA"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("vigilancia.api.urls")),
    path("", include("tablero.urls")),
]

handler403 = "tablero.views.acceso_denegado"
handler404 = "tablero.views.no_encontrado"

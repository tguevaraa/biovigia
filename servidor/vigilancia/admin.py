"""Panel técnico. Los eventos son de solo lectura: el registro lo escribe la visión."""
from django.contrib import admin

from .models import (
    AccionCorrectiva,
    Box,
    CambioEstado,
    Evento,
    Parametros,
    Recambio,
    Recipiente,
    TramoObservado,
    Zona,
)


class RecipienteEnLinea(admin.TabularInline):
    model = Recipiente
    extra = 0
    fields = ("tipo", "estado", "contaminado_desde")
    readonly_fields = ("estado", "contaminado_desde")


@admin.register(Box)
class BoxAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo", "ultimo_latido", "fps_medido",
                    "camara_conectada", "cola_pendientes")
    readonly_fields = ("ultimo_latido", "fps_medido", "camara_conectada", "zonas_alineadas",
                       "modelo_en_uso", "cola_pendientes", "referencia_en")
    inlines = [RecipienteEnLinea]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        for tipo in ("rojo", "comun"):
            Recipiente.objects.get_or_create(box=obj, tipo=tipo)


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "ocurrido_en", "turno", "recipiente", "veredicto", "confianza",
                    "modelo")
    list_filter = ("veredicto", "turno", "recipiente__tipo")
    date_hierarchy = "ocurrido_en"
    search_fields = ("id_externo",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Recipiente)
class RecipienteAdmin(admin.ModelAdmin):
    list_display = ("__str__", "estado", "contaminado_desde")
    readonly_fields = ("estado", "contaminado_desde", "evento_causa")


@admin.register(Recambio)
class RecambioAdmin(admin.ModelAdmin):
    list_display = ("pk", "recipiente", "registrado_en", "registrado_por")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CambioEstado)
class CambioEstadoAdmin(admin.ModelAdmin):
    list_display = ("ocurrido_en", "recipiente", "estado_anterior", "estado_nuevo")

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(TramoObservado, list_display=("box", "inicio", "fin"))
admin.site.register(AccionCorrectiva, list_display=("registrada_en", "descripcion", "responsable"))
admin.site.register(Zona, list_display=("recipiente", "actualizado_en"))
admin.site.register(Parametros)

"""Panel técnico de Django para cuentas. La gestión diaria se hace en PAN-11."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Bitacora, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "rol", "is_active", "last_login")
    list_filter = ("rol", "is_active")
    fieldsets = UserAdmin.fieldsets + (("BioVigIA", {"fields": ("rol",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("BioVigIA", {"fields": ("rol",)}),)


@admin.register(Bitacora)
class BitacoraAdmin(admin.ModelAdmin):
    """Solo lectura: RNF-14 exige un registro no editable desde la aplicación."""

    list_display = ("ocurrido_en", "usuario_nombre", "accion", "detalle", "ip")
    list_filter = ("accion",)
    search_fields = ("usuario_nombre", "detalle")
    date_hierarchy = "ocurrido_en"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

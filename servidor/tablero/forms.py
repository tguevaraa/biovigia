"""Formularios de las pantallas. Solo validan forma; los rangos los decide el dominio."""
from __future__ import annotations

from datetime import timedelta

from django import forms
from django.utils import timezone

from cuentas.models import ROLES_HUMANOS, Rol
from vigilancia.models import Parametros
from vigilancia.servicios.tiempo import FUERA_DE_TURNO, turnos


def _turnos_opciones(incluir_fuera: bool = False):
    opciones = [("", "Todos")] + [(t.codigo, t.etiqueta) for t in turnos()]
    if incluir_fuera:
        opciones.append((FUERA_DE_TURNO, "Fuera de turno"))
    return opciones


class Fecha(forms.DateInput):
    input_type = "date"


class FiltroEventosForm(forms.Form):
    desde = forms.DateField(required=False, widget=Fecha(attrs={"class": "form-control"}))
    hasta = forms.DateField(required=False, widget=Fecha(attrs={"class": "form-control"}))
    turno = forms.ChoiceField(required=False, choices=(),
                              widget=forms.Select(attrs={"class": "form-select"}))
    recipiente = forms.ChoiceField(
        required=False, choices=[("", "Todos"), ("rojo", "Rojo (infeccioso)"), ("comun", "Común")],
        widget=forms.Select(attrs={"class": "form-select"}))
    veredicto = forms.ChoiceField(
        required=False,
        choices=[("", "Todos"), ("conforme", "Conforme"), ("no_conforme", "No conforme")],
        widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["turno"].choices = _turnos_opciones(incluir_fuera=True)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            self.add_error("hasta", "La fecha final no puede ser anterior a la inicial.")
        return datos


class PeriodoForm(forms.Form):
    PERIODOS = [("7", "Últimos 7 días"), ("30", "Últimos 30 días"), ("mes", "Este mes"),
                ("personalizado", "Personalizado")]
    periodo = forms.ChoiceField(required=False, choices=PERIODOS,
                                widget=forms.Select(attrs={"class": "form-select"}))
    desde = forms.DateField(required=False, widget=Fecha(attrs={"class": "form-control"}))
    hasta = forms.DateField(required=False, widget=Fecha(attrs={"class": "form-control"}))
    turno = forms.ChoiceField(required=False, choices=(),
                              widget=forms.Select(attrs={"class": "form-select"}))
    recipiente = forms.ChoiceField(
        required=False, choices=[("", "Todos"), ("rojo", "Rojo (infeccioso)"), ("comun", "Común")],
        widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["turno"].choices = _turnos_opciones()

    def como_parametros(self) -> dict:
        d = self.cleaned_data
        hoy = timezone.localdate()
        periodo = d.get("periodo") or "7"
        if periodo == "personalizado" and d.get("desde") and d.get("hasta"):
            desde, hasta = d["desde"], d["hasta"]
        elif periodo == "30":
            desde, hasta = hoy - timedelta(days=29), hoy
        elif periodo == "mes":
            desde, hasta = hoy.replace(day=1), hoy
        else:
            desde, hasta = hoy - timedelta(days=6), hoy
        return {"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                "turno": d.get("turno", ""), "recipiente": d.get("recipiente", "")}


class ParametrosForm(forms.Form):
    """Los rangos se muestran como pista; la validación definitiva la hace el dominio."""

    umbral_confianza = forms.FloatField(label="Umbral de confianza del detector")
    ventana_confirmacion_s = forms.FloatField(label="Ventana de confirmación (segundos)")
    k_confirmacion = forms.IntegerField(label="k: observaciones dentro de la zona")
    n_confirmacion = forms.IntegerField(label="N: observaciones consideradas")
    fps_muestreo = forms.IntegerField(label="Frecuencia de muestreo (fps)")
    retencion_dias = forms.IntegerField(label="Retención de evidencia (días)")

    AYUDAS = {
        "umbral_confianza": "Detecciones por debajo de este valor se ignoran.",
        "ventana_confirmacion_s": "Tiempo que la gasa debe seguir ausente dentro de la zona "
                                  "para confirmar el descarte.",
        "k_confirmacion": "Regla k-de-N: de las últimas N observaciones, al menos k dentro de "
                          "la misma zona.",
        "n_confirmacion": "Tamaño de la ventana de observaciones de la regla k-de-N.",
        "fps_muestreo": "Nunca por debajo de 15 (RNF-09).",
        "retencion_dias": "Máximo 90 días (RNF-17). El evento se conserva; solo se borra el "
                          "recorte.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre, campo in self.fields.items():
            minimo, maximo = Parametros.RANGOS[nombre]
            campo.widget.attrs.update({
                "class": "form-control", "min": minimo, "max": maximo,
                "step": "0.01" if isinstance(campo, forms.FloatField) else "1",
                "inputmode": "decimal",
            })
            campo.help_text = f"{self.AYUDAS[nombre]} Rango admitido: {minimo} a {maximo}."


class UsuarioForm(forms.Form):
    username = forms.CharField(label="Usuario", max_length=150)
    first_name = forms.CharField(label="Nombres", max_length=150, required=False)
    last_name = forms.CharField(label="Apellidos", max_length=150, required=False)
    email = forms.EmailField(label="Correo", required=False)
    rol = forms.ChoiceField(label="Rol", choices=[(r.value, r.label) for r in ROLES_HUMANOS],
                            initial=Rol.OPERATIVO)
    password = forms.CharField(label="Contraseña", required=False,
                               widget=forms.PasswordInput(render_value=False))
    is_active = forms.BooleanField(label="Cuenta activa", required=False, initial=True)

    def __init__(self, *args, creando: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = creando
        for nombre, campo in self.fields.items():
            if nombre == "is_active":
                campo.widget.attrs["class"] = "form-check-input"
            elif nombre == "rol":
                campo.widget.attrs["class"] = "form-select"
            else:
                campo.widget.attrs["class"] = "form-control"
        if creando:
            self.fields["password"].required = True
            self.fields["password"].help_text = "Mínimo 8 caracteres, no solo números."
            del self.fields["is_active"]
        else:
            self.fields["username"].disabled = True
            self.fields["password"].help_text = "Déjala vacía para no cambiarla."

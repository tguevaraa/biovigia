"""Vistas de plantilla (View del patrón MVT) para las pantallas PAN-01 a PAN-12.

Cada vista: comprueba el rol con ``requiere_acceso``, llama a un servicio de dominio y
entrega el resultado a una plantilla. No hay reglas de negocio aquí.
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from cuentas.models import AccionBitacora, Rol, Usuario
from cuentas.permisos import puede, requiere_acceso
from cuentas.servicios import (
    ErrorGestionUsuarios,
    actualizar_usuario,
    crear_usuario,
    pantalla_inicial,
    registrar,
)
from vigilancia.models import Box, Parametros, TipoRecipiente
from vigilancia.servicios import (
    acciones,
    configuracion,
    eventos,
    recipientes,
    reportes,
    tablero,
)
from vigilancia.servicios.errores import ErrorDominio, NoEncontrado, RecipienteNoContaminado
from vigilancia.servicios.retencion import depurar_si_corresponde
from vigilancia.servicios.tiempo import hoy, turno_actual, turno_por_codigo, turnos

from .forms import FiltroEventosForm, ParametrosForm, PeriodoForm, UsuarioForm


# --- Sesión (PAN-01, PAN-12) -------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def login_vista(request):
    if request.user.is_authenticated and request.user.es_humano:
        return redirect(pantalla_inicial(request.user))
    form = AuthenticationForm(request, data=request.POST or None)
    form.fields["username"].widget.attrs.update({"autofocus": True, "class": "form-control"})
    form.fields["password"].widget.attrs.update({"class": "form-control"})
    if request.method == "POST":
        if form.is_valid() and form.get_user().es_humano:
            usuario = form.get_user()
            login(request, usuario)
            registrar(request, AccionBitacora.INICIO_SESION, "Web", usuario)
            siguiente = request.POST.get("next") or request.GET.get("next")
            if siguiente and url_has_allowed_host_and_scheme(
                    siguiente, {request.get_host()}, request.is_secure()):
                return redirect(siguiente)
            return redirect(pantalla_inicial(usuario))
        registrar(request, AccionBitacora.INICIO_FALLIDO,
                  (request.POST.get("username") or "")[:150])
        messages.error(request, "Usuario o contraseña incorrectos.")
        estado = 401
    else:
        estado = 200
    return render(request, "tablero/login.html", {"form": form,
                                                  "next": request.GET.get("next", "")},
                  status=estado)


@require_POST
def logout_vista(request):
    if request.user.is_authenticated:
        registrar(request, AccionBitacora.CIERRE_SESION, "Web")
    logout(request)
    return redirect("tablero:login")


def inicio(request):
    if not request.user.is_authenticated:
        return redirect("tablero:login")
    return redirect(pantalla_inicial(request.user))


@requiere_acceso("cuenta")
@require_http_methods(["GET", "POST"])
def mi_cuenta(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    for campo in form.fields.values():
        campo.widget.attrs["class"] = "form-control"
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        update_session_auth_hash(request, usuario)
        registrar(request, AccionBitacora.USUARIOS, "Cambió su contraseña")
        messages.success(request, "Contraseña actualizada.")
        return redirect("tablero:mi_cuenta")
    return render(request, "tablero/mi_cuenta.html", {"form": form, "nav": "cuenta"})


# --- Tablero y eventos (PAN-02, PAN-03, PAN-04) ------------------------------------------------

def _fecha_turno(request):
    try:
        fecha = date.fromisoformat(request.GET["fecha"]) if request.GET.get("fecha") else hoy()
    except ValueError:
        fecha = hoy()
    turno = turno_por_codigo(request.GET.get("turno", "")) or turno_actual()
    return fecha, turno


@requiere_acceso("tablero")
def principal(request):
    depurar_si_corresponde()
    fecha, turno = _fecha_turno(request)
    resumen = tablero.resumen_turno(fecha, turno)
    inicio, fin = turno.rango(fecha)
    ultimos = eventos.paginar(
        eventos.filtrar({"desde": fecha, "hasta": fecha, "turno": turno.codigo}), 1)
    maximo = max([h["total"] or 0 for h in resumen["por_hora"]] + [1])
    return render(request, "tablero/principal.html", {
        "nav": "principal", "r": resumen, "fecha": fecha, "turno": turno, "turnos": turnos(),
        "ultimos": ultimos, "maximo": maximo,
        "recipientes": recipientes.recipientes_activos(),
        "inicio_turno": inicio, "fin_turno": fin,
        "suma_texto": _suma_texto(resumen["por_hora"]),
    })


def _suma_texto(por_hora) -> str:
    """Alternativa textual del gráfico: la suma explícita de las barras (sección 8.6)."""
    totales = [h["total"] for h in por_hora if h["total"] is not None]
    nc = [h["no_conformes"] for h in por_hora if h["no_conformes"] is not None]
    if not totales:
        return "Todavía no hay horas observadas en este turno."
    texto = (f"Suma del turno: {' + '.join(map(str, totales))} = {sum(totales)} descartes y "
             f"{' + '.join(map(str, nc))} = {sum(nc)} no conformes.")
    sin_obs = [h["hora"] for h in por_hora if h["estado"] in ("sin_observar", "parcial")]
    if sin_obs:
        texto += (f" Con tramos sin observar en: {', '.join(sin_obs)}; esos tramos no cuentan "
                  "como cero.")
    return texto


@requiere_acceso("eventos")
def lista_eventos(request):
    form = FiltroEventosForm(request.GET or None)
    filtros = form.cleaned_data if form.is_valid() else {}
    try:
        pagina = eventos.paginar(eventos.filtrar(filtros), request.GET.get("pagina"))
    except ErrorDominio as exc:
        messages.warning(request, exc.detalle)
        pagina = eventos.paginar(eventos.filtrar({}), 1)
    consulta = request.GET.copy()
    consulta.pop("pagina", None)
    return render(request, "tablero/eventos.html", {
        "nav": "eventos", "form": form, "pagina": pagina, "consulta": consulta.urlencode(),
        "hay_filtros": any(filtros.values()) if filtros else False,
    })


@requiere_acceso("eventos")
def evento_detalle(request, evento_id: int):
    try:
        evento = eventos.obtener(evento_id)
    except NoEncontrado as exc:
        raise Http404 from exc
    return render(request, "tablero/evento_detalle.html", {
        "nav": "eventos", "e": evento,
        "estado_tras": eventos.estado_recipiente_tras(evento),
        "acciones_evento": evento.acciones.all(),
    })


@requiere_acceso("evidencia")
def evidencia(request, evento_id: int):
    try:
        archivo = eventos.abrir_evidencia(eventos.obtener(evento_id), request.user, request)
    except NoEncontrado as exc:
        raise Http404 from exc
    respuesta = FileResponse(archivo, content_type="image/jpeg")
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


# --- Recipientes y recambio (PAN-05, PAN-06) -------------------------------------------------

@requiere_acceso("recipientes")
def estado_recipientes(request):
    lista = list(recipientes.recipientes_activos())
    boxes: dict[str, dict] = {}
    for r in lista:
        grupo = boxes.setdefault(r.box.codigo, {"box": r.box, "items": []})
        grupo["items"].append({"r": r, "ultimo": recipientes.ultimo_cambio(r)})
    return render(request, "tablero/recipientes.html", {
        "nav": "recipientes",
        "boxes": boxes.values(),
        "contaminados": [r for r in lista if r.contaminado],
        "normales": [r for r in lista if not r.contaminado],
        "cambios": recipientes.cambios_de_hoy(),
        "ve_eventos": puede(request.user, "eventos"),
        "puede_recambio": puede(request.user, "recambio"),
        "vista_movil": request.user.rol == Rol.OPERATIVO,
    })


@requiere_acceso("recambio")
@require_http_methods(["GET", "POST"])
def registrar_recambio(request, box: str, tipo: str):
    try:
        recipiente = recipientes.obtener_recipiente(box, tipo)
    except NoEncontrado as exc:
        raise Http404 from exc
    if request.method == "POST":
        try:
            recipientes.registrar_recambio(box, tipo, request.user, request)
        except RecipienteNoContaminado as exc:
            messages.info(request, exc.detalle)  # aviso informativo, no error rojo (HU-03)
        else:
            messages.success(request, f"Recambio registrado. {recipiente} volvió a estado normal; "
                                      "el evento se conserva en el historial.")
        return redirect("tablero:recipientes")
    if not recipiente.contaminado:
        messages.info(request, RecipienteNoContaminado().detalle)
        return redirect("tablero:recipientes")
    return render(request, "tablero/recambio.html", {"nav": "recipientes", "r": recipiente,
                                                     "vista_movil": request.user.rol ==
                                                     Rol.OPERATIVO})


# --- Reportes y acciones (PAN-07, PAN-08) ----------------------------------------------------

@requiere_acceso("reportes")
def vista_reportes(request):
    form = PeriodoForm(request.GET or None)
    params = form.como_parametros() if form.is_valid() else {}
    try:
        periodo = reportes.periodo_desde(params)
    except ErrorDominio as exc:
        messages.warning(request, exc.detalle)
        periodo = reportes.periodo_desde({})
    ind = reportes.calcular(periodo)
    maximo = max([d["total"] or 0 for d in ind.evolucion_diaria] + [1])
    return render(request, "tablero/reportes.html", {
        "nav": "reportes", "form": form, "ind": ind, "maximo": maximo,
        "consulta": request.GET.urlencode(),
    })


@requiere_acceso("reportes")
def exportar(request):
    form = PeriodoForm(request.GET or None)
    params = form.como_parametros() if form.is_valid() else {}
    try:
        exportador = reportes.exportador_para(request.GET.get("formato", "csv"))
        periodo = reportes.periodo_desde(params)
    except ErrorDominio as exc:
        messages.warning(request, exc.detalle)
        return redirect("tablero:reportes")
    ind = reportes.calcular(periodo)
    destino = f"{reverse('tablero:reportes')}?{form.data.urlencode() if form.data else ''}"
    if not ind.hay_eventos:  # HU-04, criterio 3: informar en lugar de un archivo vacío
        messages.info(request, "El periodo seleccionado no tiene eventos; no se generó ningún "
                               "archivo.")
        return redirect(destino)
    contenido = exportador.generar(ind)
    registrar(request, AccionBitacora.EXPORTAR,
              f"{exportador.formato.upper()} · {periodo.descripcion}")
    respuesta = HttpResponse(contenido, content_type=exportador.tipo_mime)
    respuesta["Content-Disposition"] = f'attachment; filename="{exportador.nombre_archivo(periodo)}"'
    return respuesta


@requiere_acceso("acciones")
@require_http_methods(["GET", "POST"])
def vista_acciones(request):
    if request.method == "POST":
        try:
            acciones.registrar_accion(
                request.POST.get("descripcion", ""), request.POST.getlist("eventos"),
                request.user, request.POST.get("responsable", ""), request)
        except ErrorDominio as exc:
            messages.error(request, f"No se guardó la acción: {exc.detalle}.")
        else:
            messages.success(request, "Acción correctiva registrada.")
            return redirect("tablero:acciones")
    preseleccion = set(request.GET.getlist("evento"))
    return render(request, "tablero/acciones.html", {
        "nav": "acciones",
        "pendientes": acciones.no_conformes_sin_accion()[:50],
        "acciones": acciones.listar()[:50],
        "preseleccion": preseleccion,
        "datos": request.POST,
    })


# --- Configuración (PAN-09, PAN-10, PAN-11) ----------------------------------------------------

@requiere_acceso("zonas")
def zonas(request):
    boxes = list(Box.objects.filter(activo=True))
    if not boxes:
        messages.warning(request, "No hay boxes registrados. Ejecuta: python manage.py sembrar")
        return render(request, "tablero/zonas.html", {"nav": "config", "tab": "zonas",
                                                      "box": None, "boxes": []})
    codigo = request.GET.get("box") or boxes[0].codigo
    box = next((b for b in boxes if b.codigo == codigo), boxes[0])
    return render(request, "tablero/zonas.html", {
        "nav": "config", "tab": "zonas", "box": box, "boxes": boxes,
        "camara": configuracion.estado_camara(box),
        "zonas": configuracion.zonas_de(box),
        "tipos": TipoRecipiente.choices,
    })


@requiere_acceso("parametros")
@require_http_methods(["GET", "POST"])
def parametros(request):
    actual = Parametros.actual()
    form = ParametrosForm(request.POST or None, initial=actual.como_dict())
    if request.method == "POST":
        if form.is_valid():
            try:
                configuracion.actualizar_parametros(form.cleaned_data, request.user, request)
            except ErrorDominio as exc:
                form.add_error(exc.campo, exc.detalle)
            else:
                messages.success(request, "Parámetros guardados. El servicio de visión los "
                                          "aplica en su siguiente consulta (≤ 30 s).")
                return redirect("tablero:parametros")
        messages.error(request, "No se guardó ningún cambio: revisa los valores marcados. "
                                "Se conservan los valores anteriores.")
    return render(request, "tablero/parametros.html", {
        "nav": "config", "tab": "parametros", "form": form, "actual": actual,
    })


@requiere_acceso("usuarios")
@require_http_methods(["GET", "POST"])
def usuarios(request):
    form = UsuarioForm(request.POST or None, creando=True)
    if request.method == "POST" and form.is_valid():
        try:
            nuevo = crear_usuario(form.cleaned_data, request.user, request)
        except ErrorGestionUsuarios as exc:
            form.add_error(exc.campo if exc.campo in form.fields else None, exc.detalle)
        else:
            messages.success(request, f"Cuenta {nuevo.username} creada.")
            return redirect("tablero:usuarios")
    lista = Usuario.objects.exclude(rol=Rol.SERVICIO).order_by("-is_active", "username")
    return render(request, "tablero/usuarios.html", {
        "nav": "config", "tab": "usuarios", "form": form, "usuarios": lista,
    })


@requiere_acceso("usuarios")
@require_http_methods(["GET", "POST"])
def usuario_editar(request, usuario_id: int):
    try:
        usuario = Usuario.objects.exclude(rol=Rol.SERVICIO).get(pk=usuario_id)
    except Usuario.DoesNotExist as exc:
        raise Http404 from exc
    form = UsuarioForm(request.POST or None, creando=False, initial={
        "username": usuario.username, "first_name": usuario.first_name,
        "last_name": usuario.last_name, "email": usuario.email, "rol": usuario.rol,
        "is_active": usuario.is_active})
    if request.method == "POST" and form.is_valid():
        datos = dict(form.cleaned_data)
        datos.pop("username", None)
        try:
            actualizar_usuario(usuario, datos, request.user, request)
        except ErrorGestionUsuarios as exc:
            form.add_error(exc.campo if exc.campo in form.fields else None, exc.detalle)
        else:
            messages.success(request, f"Cuenta {usuario.username} actualizada.")
            return redirect("tablero:usuarios")
    return render(request, "tablero/usuario_editar.html", {
        "nav": "config", "tab": "usuarios", "form": form, "u": usuario,
    })


# --- Errores -------------------------------------------------------------------------------------

def acceso_denegado(request, exception=None):
    """Aviso de acceso no autorizado con regreso a la pantalla inicial (RNF-13, prueba paso 8)."""
    if request.path.startswith("/api/"):
        return HttpResponse('{"error": "acceso_denegado"}', status=403,
                            content_type="application/json")
    destino = reverse("tablero:login")
    if request.user.is_authenticated:
        registrar(request, AccionBitacora.ACCESO_DENEGADO, request.path[:300])
        destino = reverse(pantalla_inicial(request.user))
    return render(request, "tablero/403.html", {"destino": destino}, status=403)


def no_encontrado(request, exception=None):
    destino = reverse(pantalla_inicial(request.user)) if request.user.is_authenticated else \
        reverse("tablero:login")
    return render(request, "tablero/404.html", {"destino": destino}, status=404)

"""Capa de API v1 (DRF). Cada vista valida la forma, llama a un servicio y responde.

Las rutas y los cuerpos siguen ``docs/contrato-api.md``. El rol se toma siempre de la
sesión o del token, nunca de un parámetro (contrato v1, regla 6).
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth import authenticate, login, logout
from django.http import FileResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from cuentas.models import AccionBitacora, Rol, Usuario
from cuentas.permisos import AccesoPorRol
from cuentas.servicios import (
    ErrorGestionUsuarios,
    actualizar_usuario,
    crear_usuario,
    pantalla_inicial,
    registrar,
)

from ..models import Parametros
from ..servicios import (
    acciones,
    configuracion,
    eventos,
    ingesta,
    observacion,
    recipientes,
    reportes,
    tablero,
)
from ..servicios.errores import ErrorValidacion, NoEncontrado
from ..servicios.retencion import depurar_si_corresponde
from ..servicios.tiempo import hoy, turno_actual, turno_por_codigo
from . import serializadores as s
from .errores import respuesta_error


class VistaBase(APIView):
    permission_classes = [IsAuthenticated, AccesoPorRol]

    @staticmethod
    def validar(serializador_cls, datos, **kwargs):
        ser = serializador_cls(data=datos, **kwargs)
        ser.is_valid(raise_exception=True)
        return ser.validated_data


# --- Autenticación (PAN-01, PAN-12) ------------------------------------------------------------

class LoginVista(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        datos = VistaBase.validar(s.LoginSerializer, request.data)
        usuario = authenticate(request, username=datos["username"], password=datos["password"])
        if usuario is None or not usuario.es_humano:
            registrar(request, AccionBitacora.INICIO_FALLIDO, datos["username"][:150])
            return respuesta_error("credenciales", "Usuario o contraseña incorrectos.",
                                   status.HTTP_401_UNAUTHORIZED)
        login(request, usuario)
        registrar(request, AccionBitacora.INICIO_SESION, "API", usuario)
        return Response({"rol": usuario.rol, "pantalla_inicial": reverse(pantalla_inicial(usuario)),
                         "usuario": s.usuario_salida(usuario)})


class LogoutVista(VistaBase):
    recurso = "cuenta"

    def post(self, request):
        registrar(request, AccionBitacora.CIERRE_SESION, "API")
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class YoVista(VistaBase):
    recurso = "cuenta"

    def get(self, request):
        return Response({"usuario": s.usuario_salida(request.user)})


# --- Eventos (ingesta, PAN-03, PAN-04) -------------------------------------------------------

class EventosVista(VistaBase):
    recursos = {"GET": "eventos", "POST": "ingesta"}

    def post(self, request):
        datos = self.validar(s.EventoEntradaSerializer, request.data)
        r = ingesta.registrar_evento(datos)
        cuerpo = {
            "id": r.evento.pk,
            "id_externo": r.evento.id_externo,
            "veredicto": r.evento.veredicto,
            "recipiente": r.evento.recipiente.tipo,
            "estado_recipiente": r.estado_recipiente,
            "evidencia_guardada": r.evidencia_guardada,
        }
        if not r.creado:
            cuerpo["duplicado"] = True
            return Response(cuerpo, status=status.HTTP_200_OK)
        return Response(cuerpo, status=status.HTTP_201_CREATED)

    def get(self, request):
        pagina = eventos.paginar(eventos.filtrar(request.query_params),
                                 request.query_params.get("pagina"))
        return Response({
            "total": pagina.total, "pagina": pagina.pagina, "paginas": pagina.paginas,
            "items": [s.evento_resumen(e) for e in pagina.items],
        })


class EventoDetalleVista(VistaBase):
    recurso = "eventos"

    def get(self, request, evento_id: int):
        return Response(s.evento_detalle(eventos.obtener(evento_id)))


class EventoEvidenciaVista(VistaBase):
    recurso = "evidencia"

    def get(self, request, evento_id: int):
        archivo = eventos.abrir_evidencia(eventos.obtener(evento_id), request.user, request)
        respuesta = FileResponse(archivo, content_type="image/jpeg")
        respuesta["Cache-Control"] = "private, no-store"
        return respuesta


# --- Tablero y recipientes (PAN-02, PAN-05, PAN-06) ------------------------------------------

def leer_fecha_turno(params) -> tuple[date, object]:
    try:
        fecha = date.fromisoformat(params["fecha"]) if params.get("fecha") else hoy()
    except ValueError as exc:
        raise ErrorValidacion("formato AAAA-MM-DD", campo="fecha") from exc
    codigo = params.get("turno")
    turno = turno_por_codigo(codigo) if codigo else turno_actual()
    if turno is None:
        raise ErrorValidacion("turno no válido", campo="turno")
    return fecha, turno


class TableroVista(VistaBase):
    recurso = "tablero"

    def get(self, request):
        depurar_si_corresponde()
        fecha, turno = leer_fecha_turno(request.query_params)
        return Response(tablero.resumen_turno(fecha, turno))


class RecipientesVista(VistaBase):
    recurso = "recipientes"

    def get(self, request):
        ve_eventos = request.user.rol in (Rol.ADMIN, Rol.SUPERVISOR)
        items = []
        for r in recipientes.recipientes_activos():
            item = {"box": r.box.codigo, "tipo": r.tipo, "estado": r.estado}
            if r.contaminado and r.contaminado_desde:
                item["contaminado_desde"] = timezone.localtime(r.contaminado_desde).isoformat(
                    timespec="seconds")
                if ve_eventos:
                    item["evento_causa_id"] = r.evento_causa_id
            items.append(item)
        cambios = []
        for c in recipientes.cambios_de_hoy():
            fila = {"hora": c.hora.strftime("%H:%M"), "box": c.recipiente.box.codigo,
                    "tipo": c.recipiente.tipo, "de": c.de, "a": c.a}
            if c.recambio_id:
                fila["recambio_id"] = c.recambio_id
            if c.evento_id and ve_eventos:  # el personal de limpieza no accede a eventos
                fila["evento_id"] = c.evento_id
            cambios.append(fila)
        return Response({"actualizado_en": timezone.localtime().isoformat(timespec="seconds"),
                         "items": items, "cambios_hoy": cambios})


class RecambiosVista(VistaBase):
    recurso = "recambio"

    def post(self, request):
        datos = self.validar(s.RecambioEntradaSerializer, request.data)
        recambio = recipientes.registrar_recambio(datos["box"], datos["tipo"], request.user,
                                                  request)
        return Response({
            "id": recambio.pk, "estado": "normal",
            "registrado_en": timezone.localtime(recambio.registrado_en).isoformat(
                timespec="seconds"),
        }, status=status.HTTP_201_CREATED)


# --- Reportes y acciones (PAN-07, PAN-08) ----------------------------------------------------

class ReportesVista(VistaBase):
    recurso = "reportes"

    def get(self, request):
        periodo = reportes.periodo_desde(request.query_params)
        return Response(reportes.calcular(periodo).como_dict())


class ReportesExportarVista(VistaBase):
    recurso = "reportes"

    def get(self, request):
        exportador = reportes.exportador_para(request.query_params.get("formato", "csv"))
        periodo = reportes.periodo_desde(request.query_params)
        indicadores = reportes.calcular(periodo)
        if not indicadores.hay_eventos:  # HU-04, criterio 3
            return Response(status=status.HTTP_204_NO_CONTENT)
        contenido = exportador.generar(indicadores)
        registrar(request, AccionBitacora.EXPORTAR,
                  f"{exportador.formato.upper()} · {periodo.descripcion}")
        respuesta = HttpResponse(contenido, content_type=exportador.tipo_mime)
        respuesta["Content-Disposition"] = (
            f'attachment; filename="{exportador.nombre_archivo(periodo)}"')
        return respuesta


class AccionesVista(VistaBase):
    recurso = "acciones"

    def get(self, request):
        return Response({
            "items": [{
                "id": a.pk, "descripcion": a.descripcion, "responsable": a.responsable,
                "registrada_por": a.registrada_por.nombre_visible,
                "registrada_en": timezone.localtime(a.registrada_en).isoformat(
                    timespec="seconds"),
                "eventos": [e.pk for e in a.eventos.all()],
            } for a in acciones.listar()],
            "pendientes": [s.evento_resumen(e) for e in acciones.no_conformes_sin_accion()[:100]],
        })

    def post(self, request):
        datos = self.validar(s.AccionEntradaSerializer, request.data)
        accion = acciones.registrar_accion(datos["descripcion"], datos["eventos"], request.user,
                                           datos.get("responsable", ""), request)
        return Response({"id": accion.pk}, status=status.HTTP_201_CREATED)


# --- Configuración (PAN-09, PAN-10) ------------------------------------------------------------

class ZonasVista(VistaBase):
    recurso = "zonas"

    def get(self, request, box: str):
        b = configuracion.obtener_box(box)
        return Response({"box": b.codigo, "camara": configuracion.estado_camara(b),
                         "zonas": configuracion.zonas_de(b)})

    def put(self, request, box: str):
        b = configuracion.obtener_box(box)
        datos = self.validar(s.ZonasEntradaSerializer, request.data)
        configuracion.guardar_zonas(b, [dict(z) for z in datos["zonas"]], request.user, request)
        return Response({"box": b.codigo, "zonas": configuracion.zonas_de(b)})


class ReferenciaVista(VistaBase):
    recursos = {"GET": "zonas", "PUT": "ingesta"}

    def get(self, request, box: str):
        b = configuracion.obtener_box(box)
        if not b.referencia:
            raise NoEncontrado("Todavía no hay fotograma de referencia para este box.")
        respuesta = FileResponse(b.referencia.open("rb"), content_type="image/jpeg")
        respuesta["Cache-Control"] = "private, no-store"
        return respuesta

    def put(self, request, box: str):
        b = configuracion.obtener_box(box)
        datos = self.validar(s.ReferenciaSerializer, request.data)
        configuracion.guardar_referencia(b, datos["imagen_jpeg_b64"])
        return Response({"box": b.codigo, "referencia_en": b.referencia_en.isoformat()})


class ParametrosVista(VistaBase):
    recurso = "parametros"

    def get(self, request):
        return Response({"valores": Parametros.actual().como_dict(),
                         "limites": configuracion.limites()})

    def put(self, request):
        if not isinstance(request.data, dict):
            raise ErrorValidacion("el cuerpo debe ser un objeto JSON")
        p = configuracion.actualizar_parametros(dict(request.data), request.user, request)
        return Response({"valores": p.como_dict(), "limites": configuracion.limites()})


# --- Servicio de visión: latidos y configuración ----------------------------------------------

class SaludVista(VistaBase):
    recurso = "ingesta"

    def post(self, request):
        datos = self.validar(s.SaludSerializer, request.data)
        box = configuracion.obtener_box(datos["box"])
        observacion.registrar_latido(box, datos)
        return Response({"ok": True, "recibido_en": timezone.localtime().isoformat(
            timespec="seconds")})


class ConfiguracionVisionVista(VistaBase):
    recurso = "ingesta"

    def get(self, request):
        box = configuracion.obtener_box(request.query_params.get("box", ""))
        return Response(configuracion.configuracion_para_vision(box))


# --- Usuarios (PAN-11) ---------------------------------------------------------------------------

def _error_usuarios(exc: ErrorGestionUsuarios):
    return respuesta_error("validacion", exc.detalle, status.HTTP_422_UNPROCESSABLE_ENTITY,
                           exc.campo)


class UsuariosVista(VistaBase):
    recurso = "usuarios"

    def get(self, request):
        qs = Usuario.objects.exclude(rol=Rol.SERVICIO).order_by("username")
        return Response({"items": [s.usuario_salida(u) for u in qs]})

    def post(self, request):
        try:
            usuario = crear_usuario(dict(request.data), request.user, request)
        except ErrorGestionUsuarios as exc:
            return _error_usuarios(exc)
        return Response(s.usuario_salida(usuario), status=status.HTTP_201_CREATED)


class UsuarioDetalleVista(VistaBase):
    recurso = "usuarios"

    def patch(self, request, usuario_id: int):
        try:
            usuario = Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist as exc:
            raise NoEncontrado("La cuenta no existe.") from exc
        try:
            usuario = actualizar_usuario(usuario, dict(request.data), request.user, request)
        except ErrorGestionUsuarios as exc:
            return _error_usuarios(exc)
        return Response(s.usuario_salida(usuario))

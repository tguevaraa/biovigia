"""Pruebas del contrato v1 y de la prueba de aceptación del MVP (docs/prueba-aceptacion.md).

    python manage.py test
"""
from __future__ import annotations

import base64
import io
import shutil
import tempfile
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from cuentas.models import Bitacora, Rol, Usuario
from vigilancia.models import Box, Evento, Parametros, Recipiente, TramoObservado
from vigilancia.servicios.recipientes import crear_box
from vigilancia.servicios.retencion import depurar_evidencia_vencida

MEDIA_TEMPORAL = tempfile.mkdtemp(prefix="biovigia-test-")


def jpeg_b64(color=(200, 30, 30)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


def cuerpo_evento(n: int, recipiente: str, **extra) -> dict:
    momento = timezone.localtime() - timedelta(minutes=1, seconds=n)
    datos = {
        "id_externo": f"box2-prueba-{n:03d}",
        "box": "box-2",
        "recipiente": recipiente,
        "veredicto": "conforme" if recipiente == "rojo" else "no_conforme",
        "confianza": 0.91,
        "ocurrido_en": momento.isoformat(timespec="milliseconds"),
        "modelo": "prueba",
        "rasgos": {"fotogramas_confirmacion": 3},
    }
    datos.update(extra)
    return datos


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAL)
class BaseAPI(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)

    def setUp(self):
        self.box = crear_box("box-2", "Box 2")
        self.servicio = Usuario.objects.create_user("vision-box-2", rol=Rol.SERVICIO)
        self.token = Token.objects.create(user=self.servicio)
        self.vision = APIClient()
        self.vision.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.admin = Usuario.objects.create_user("admin", password="ClaveSegura-1", rol=Rol.ADMIN)
        self.supervisor = Usuario.objects.create_user("sup", password="ClaveSegura-1",
                                                      rol=Rol.SUPERVISOR)
        self.operativo = Usuario.objects.create_user("limp", password="ClaveSegura-1",
                                                     rol=Rol.OPERATIVO)

    def cliente(self, usuario) -> APIClient:
        c = APIClient()
        c.force_authenticate(usuario)
        return c

    def enviar(self, datos):
        return self.vision.post("/api/v1/eventos", datos, format="json")


class IngestaTests(BaseAPI):
    def test_crea_evento_y_contamina_el_comun(self):
        r = self.enviar(cuerpo_evento(1, "comun", evidencia_jpeg_b64=jpeg_b64()))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["veredicto"], "no_conforme")
        self.assertEqual(r.data["estado_recipiente"], "contaminado")
        self.assertTrue(r.data["evidencia_guardada"])
        comun = Recipiente.objects.get(box=self.box, tipo="comun")
        self.assertTrue(comun.contaminado)
        self.assertEqual(comun.cambios.count(), 1)

    def test_id_externo_repetido_no_duplica(self):
        datos = cuerpo_evento(2, "comun")
        self.assertEqual(self.enviar(datos).status_code, 201)
        r = self.enviar(datos)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["duplicado"])
        self.assertEqual(Evento.objects.count(), 1)

    def test_el_servidor_recalcula_el_veredicto(self):
        r = self.enviar(cuerpo_evento(3, "rojo", veredicto="no_conforme"))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["veredicto"], "conforme")
        evento = Evento.objects.get()
        self.assertEqual(evento.veredicto_reportado, "no_conforme")

    def test_validaciones_responden_422_con_formato_del_contrato(self):
        r = self.enviar(cuerpo_evento(4, "comun", confianza=1.4))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.data, {"error": "validacion", "campo": "confianza",
                                  "detalle": "debe estar entre 0 y 1"})
        r = self.enviar(cuerpo_evento(5, "comun", ocurrido_en="2026-10-27T10:42:18"))
        self.assertEqual((r.status_code, r.data["campo"]), (422, "ocurrido_en"))
        futuro = (timezone.now() + timedelta(hours=1)).isoformat()
        r = self.enviar(cuerpo_evento(6, "comun", ocurrido_en=futuro))
        self.assertEqual((r.status_code, r.data["campo"]), (422, "ocurrido_en"))
        r = self.enviar(cuerpo_evento(7, "comun", box="box-9"))
        self.assertEqual((r.status_code, r.data["campo"]), (422, "box"))
        r = self.enviar(cuerpo_evento(8, "comun", evidencia_jpeg_b64="no-es-base64!"))
        self.assertEqual((r.status_code, r.data["campo"]), (422, "evidencia_jpeg_b64"))
        self.assertEqual(Evento.objects.count(), 0)

    def test_sin_token_responde_401(self):
        r = APIClient().post("/api/v1/eventos", cuerpo_evento(9, "rojo"), format="json")
        self.assertEqual(r.status_code, 401)

    def test_un_humano_no_puede_ingresar_eventos(self):
        r = self.cliente(self.admin).post("/api/v1/eventos", cuerpo_evento(10, "rojo"),
                                          format="json")
        self.assertEqual(r.status_code, 403)

    def test_segundo_no_conforme_no_repite_el_cambio_de_estado(self):
        self.enviar(cuerpo_evento(11, "comun"))
        self.enviar(cuerpo_evento(12, "comun"))
        comun = Recipiente.objects.get(box=self.box, tipo="comun")
        self.assertEqual(comun.cambios.count(), 1)


class RecambioTests(BaseAPI):
    def test_ciclo_contaminacion_recambio(self):
        self.enviar(cuerpo_evento(20, "comun"))
        limpieza = self.cliente(self.operativo)
        r = limpieza.post("/api/v1/recambios", {"box": "box-2", "tipo": "comun"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["estado"], "normal")
        self.assertEqual(Evento.objects.count(), 1)  # el evento se conserva
        r = limpieza.post("/api/v1/recambios", {"box": "box-2", "tipo": "comun"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["error"], "no_contaminado")

    def test_supervisor_no_registra_recambios(self):
        r = self.cliente(self.supervisor).post("/api/v1/recambios",
                                               {"box": "box-2", "tipo": "comun"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_limpieza_no_ve_el_evento_causa(self):
        self.enviar(cuerpo_evento(21, "comun"))
        r = self.cliente(self.operativo).get("/api/v1/recipientes")
        comun = next(i for i in r.data["items"] if i["tipo"] == "comun")
        self.assertNotIn("evento_causa_id", comun)
        self.assertTrue(all("evento_id" not in c for c in r.data["cambios_hoy"]))
        r = self.cliente(self.supervisor).get("/api/v1/recipientes")
        comun = next(i for i in r.data["items"] if i["tipo"] == "comun")
        self.assertIn("evento_causa_id", comun)


class TableroTests(BaseAPI):
    def test_sin_tramos_las_horas_pasadas_van_en_null(self):
        r = self.cliente(self.supervisor).get("/api/v1/tablero")
        self.assertEqual(r.status_code, 200)
        for hora in r.data["por_hora"]:
            if hora["estado"] in ("sin_observar", "pendiente"):
                self.assertIsNone(hora["total"])
            self.assertNotEqual(hora.get("estado"), "observado")

    def test_tramo_observado_da_cero_y_no_null(self):
        ahora = timezone.localtime()
        inicio = ahora.replace(minute=0, second=0, microsecond=0)
        if inicio == ahora:
            inicio -= timedelta(hours=1)
        TramoObservado.objects.create(box=self.box, inicio=inicio - timedelta(hours=1), fin=ahora)
        r = self.cliente(self.supervisor).get(
            "/api/v1/tablero", {"fecha": ahora.date().isoformat()})
        actuales = [h for h in r.data["por_hora"] if h["en_curso"]]
        if actuales:  # solo si la prueba corre dentro de un turno
            self.assertEqual(actuales[0]["total"], 0)
            self.assertEqual(actuales[0]["estado"], "observado")

    def test_cumplimiento_es_null_sin_descartes(self):
        r = self.cliente(self.supervisor).get("/api/v1/tablero")
        self.assertIsNone(r.data["kpis"]["cumplimiento"])

    def test_limpieza_no_entra_al_tablero(self):
        self.assertEqual(self.cliente(self.operativo).get("/api/v1/tablero").status_code, 403)
        self.assertEqual(self.cliente(self.operativo).get("/api/v1/eventos").status_code, 403)


class EventosConsultaTests(BaseAPI):
    def test_filtros_y_detalle_con_evidencia_auditada(self):
        for n in range(5):
            self.enviar(cuerpo_evento(30 + n, "rojo"))
        self.enviar(cuerpo_evento(40, "comun", evidencia_jpeg_b64=jpeg_b64()))
        sup = self.cliente(self.supervisor)
        r = sup.get("/api/v1/eventos", {"veredicto": "no_conforme"})
        self.assertEqual(r.data["total"], 1)
        r = sup.get("/api/v1/eventos", {"recipiente": "rojo"})
        self.assertEqual(r.data["total"], 5)
        r = sup.get("/api/v1/eventos", {"recipiente": "azul"})
        self.assertEqual(r.status_code, 422)
        evento = Evento.objects.get(veredicto="no_conforme")
        r = sup.get(f"/api/v1/eventos/{evento.pk}")
        self.assertTrue(r.data["evidencia"]["disponible"])
        self.assertEqual(r.data["estado_recipiente_tras_evento"], "contaminado")
        r = sup.get(f"/api/v1/eventos/{evento.pk}/evidencia")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertTrue(Bitacora.objects.filter(accion="ver_evidencia").exists())

    def test_retencion_borra_la_imagen_y_conserva_el_evento(self):
        datos = cuerpo_evento(50, "comun", evidencia_jpeg_b64=jpeg_b64())
        self.enviar(datos)
        Evento.objects.update(ocurrido_en=timezone.now() - timedelta(days=40))
        self.assertEqual(depurar_evidencia_vencida(), 1)  # retención por defecto: 30 días
        evento = Evento.objects.get()
        r = self.cliente(self.supervisor).get(f"/api/v1/eventos/{evento.pk}")
        self.assertEqual(r.data["evidencia"], {"disponible": False, "motivo": "retencion"})
        self.assertEqual(r.data["veredicto"], "no_conforme")


class ReportesTests(BaseAPI):
    def test_exportar_csv_pdf_y_204_sin_datos(self):
        sup = self.cliente(self.supervisor)
        r = sup.get("/api/v1/reportes/exportar", {"formato": "csv"})
        self.assertEqual(r.status_code, 204)
        self.enviar(cuerpo_evento(60, "comun"))
        r = sup.get("/api/v1/reportes/exportar", {"formato": "csv"})
        self.assertEqual(r.status_code, 200)
        texto = r.content.decode("utf-8-sig")
        self.assertTrue(texto.startswith(
            "fecha;hora;turno;box;recipiente;veredicto;confianza;accion_correctiva"))
        self.assertIn("No conforme", texto)
        r = sup.get("/api/v1/reportes/exportar", {"formato": "pdf"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))
        r = sup.get("/api/v1/reportes/exportar", {"formato": "xls"})
        self.assertEqual(r.status_code, 422)

    def test_dia_sin_observar_va_en_null_y_no_en_cero(self):
        r = self.cliente(self.supervisor).get("/api/v1/reportes")
        self.assertEqual(r.status_code, 200)
        pasados = [d for d in r.data["evolucion_diaria"] if d["estado"] != "pendiente"]
        self.assertTrue(pasados)
        for dia in pasados:
            self.assertIsNone(dia["total"])
            self.assertEqual(dia["estado"], "sin_observar")

    def test_accion_correctiva_aparece_en_el_csv(self):
        self.enviar(cuerpo_evento(61, "comun"))
        evento = Evento.objects.get()
        sup = self.cliente(self.supervisor)
        r = sup.post("/api/v1/acciones", {"descripcion": "Letrero junto al recipiente rojo",
                                          "eventos": [evento.pk]}, format="json")
        self.assertEqual(r.status_code, 201)
        texto = sup.get("/api/v1/reportes/exportar", {"formato": "csv"}).content.decode(
            "utf-8-sig")
        self.assertIn("Letrero junto al recipiente rojo", texto)


class ConfiguracionTests(BaseAPI):
    def test_parametros_fuera_de_rango_no_cambian_nada(self):
        admin = self.cliente(self.admin)
        r = admin.put("/api/v1/parametros", {"umbral_confianza": 0.6, "fps_muestreo": 5},
                      format="json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.data["campo"], "fps_muestreo")
        self.assertEqual(Parametros.actual().umbral_confianza, 0.5)
        r = admin.put("/api/v1/parametros", {"umbral_confianza": 0.6}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["valores"]["umbral_confianza"], 0.6)
        r = self.cliente(self.supervisor).put("/api/v1/parametros", {"umbral_confianza": 0.7},
                                              format="json")
        self.assertEqual(r.status_code, 403)

    def test_zonas_exigen_camara_a_15_fps(self):
        admin = self.cliente(self.admin)
        zona = {"zonas": [{"tipo": "rojo", "puntos": [[.1, .1], [.4, .1], [.4, .5], [.1, .5]]}]}
        r = admin.put("/api/v1/boxes/box-2/zonas", zona, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["error"], "camara_insuficiente")
        latido = {"box": "box-2", "camara_conectada": True, "fps": 24.0}
        self.assertEqual(self.vision.post("/api/v1/salud", latido, format="json").status_code, 200)
        r = admin.put("/api/v1/boxes/box-2/zonas", zona, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        # Reconfigurar el común no toca el rojo (HU-01, criterio 2).
        comun = {"zonas": [{"tipo": "comun", "puntos": [[.6, .1], [.9, .1], [.9, .5]]}]}
        r = admin.put("/api/v1/boxes/box-2/zonas", comun, format="json")
        self.assertEqual(r.data["zonas"]["rojo"]["puntos"], zona["zonas"][0]["puntos"])
        conf = self.vision.get("/api/v1/configuracion", {"box": "box-2"})
        self.assertEqual(conf.status_code, 200)
        self.assertIsNotNone(conf.data["zonas"]["comun"])

    def test_latido_con_tramos_se_fusiona(self):
        ahora = timezone.now()
        t = lambda s: (ahora - timedelta(seconds=s)).isoformat()  # noqa: E731
        for ini, fin in ((300, 200), (195, 100), (90, 10)):
            self.vision.post("/api/v1/salud", {
                "box": "box-2", "camara_conectada": True, "fps": 15,
                "tramos": [{"inicio": t(ini), "fin": t(fin)}]}, format="json")
        self.assertEqual(TramoObservado.objects.count(), 1)
        self.assertTrue(Box.objects.get().ultimo_latido)


class PantallasTests(BaseAPI):
    """Pasos 5, 6 y 8 de la prueba de aceptación desde las pantallas."""

    def test_limpieza_ve_recipientes_y_registra_recambio(self):
        self.enviar(cuerpo_evento(70, "comun"))
        self.client.force_login(self.operativo)
        r = self.client.get(reverse("tablero:recipientes"))
        self.assertContains(r, "Contaminado")
        self.assertNotContains(r, "EV-0")  # sin enlace al evento
        r = self.client.post(reverse("tablero:recambio", args=["box-2", "comun"]), follow=True)
        self.assertContains(r, "volvió a estado normal")
        r = self.client.post(reverse("tablero:recambio", args=["box-2", "comun"]), follow=True)
        self.assertContains(r, "ya está en estado normal")

    def test_limpieza_en_pan03_ve_acceso_no_autorizado(self):
        self.client.force_login(self.operativo)
        r = self.client.get(reverse("tablero:eventos"))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Acceso no autorizado", status_code=403)
        self.assertContains(r, reverse("tablero:recipientes"), status_code=403)

    def test_todas_las_pantallas_cargan_para_el_admin(self):
        self.enviar(cuerpo_evento(71, "comun", evidencia_jpeg_b64=jpeg_b64()))
        evento = Evento.objects.get()
        self.client.force_login(self.admin)
        rutas = ["principal", "eventos", "recipientes", "reportes", "acciones", "zonas",
                 "parametros", "usuarios", "mi_cuenta"]
        for nombre in rutas:
            with self.subTest(pantalla=nombre):
                self.assertEqual(self.client.get(reverse(f"tablero:{nombre}")).status_code, 200)
        self.assertEqual(self.client.get(reverse("tablero:evento", args=[evento.pk])).status_code,
                         200)
        self.assertEqual(self.client.get(reverse("tablero:recambio", args=["box-2", "comun"]))
                         .status_code, 200)
        r = self.client.get(reverse("tablero:exportar") + "?formato=pdf")
        self.assertEqual(r.status_code, 200)

    def test_login_redirige_segun_rol(self):
        r = self.client.post(reverse("tablero:login"),
                             {"username": "limp", "password": "ClaveSegura-1"})
        self.assertRedirects(r, reverse("tablero:recipientes"))
        self.client.logout()
        r = self.client.post(reverse("tablero:login"),
                             {"username": "sup", "password": "ClaveSegura-1"})
        self.assertRedirects(r, reverse("tablero:principal"))
        self.client.logout()
        r = self.client.post(reverse("tablero:login"), {"username": "sup", "password": "mal"})
        self.assertEqual(r.status_code, 401)

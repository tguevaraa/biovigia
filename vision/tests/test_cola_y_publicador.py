import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vision.cliente_api import Respuesta
from vision.cola import ColaLocal
from vision.metricas import MetricasRegistro
from vision.publicador import Publicador


def payload(n):
    return {"id_externo": f"box2-{n}", "box": "box-2", "recipiente": "comun"}


class ClienteFalso:
    def __init__(self):
        self.disponible = False
        self.recibidos = []
        self.latidos = []
        self.base = "http://falso/api/v1"

    def enviar_evento(self, cuerpo):
        if not self.disponible:
            return Respuesta(0, None, "sin conexión")
        if cuerpo["id_externo"] == "box2-malo":
            return Respuesta(422, {"error": "validacion"}, "validacion")
        duplicado = cuerpo["id_externo"] in [c["id_externo"] for c in self.recibidos]
        self.recibidos.append(cuerpo)
        return Respuesta(200 if duplicado else 201, {"veredicto": "no_conforme"})

    def enviar_latido(self, datos):
        if not self.disponible:
            return Respuesta(0, None, "sin conexión")
        self.latidos.append(datos)
        return Respuesta(200, {"ok": True})

    def obtener_configuracion(self, box):
        return Respuesta(0, None, "sin conexión")


class ColaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cola = ColaLocal(Path(self.tmp.name) / "cola.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_encolar_es_idempotente_y_ordenado(self):
        for n in (1, 2, 1):
            self.cola.encolar(payload(n))
        self.assertEqual(self.cola.pendientes(), 2)
        self.assertEqual([i for i, _, _ in self.cola.listos()], ["box2-1", "box2-2"])

    def test_reintento_con_espera(self):
        self.cola.encolar(payload(1))
        espera = self.cola.reintentar_despues("box2-1", "sin conexión")
        self.assertEqual(espera, 2.0)
        self.assertEqual(self.cola.listos(), [])  # todavía no toca
        self.assertEqual(self.cola.pendientes(), 1)

    def test_rechazo_no_se_pierde(self):
        self.cola.encolar(payload(1))
        self.cola.rechazar("box2-1", "422")
        self.assertEqual((self.cola.pendientes(), self.cola.rechazados()), (0, 1))

    def test_servidor_caido_y_luego_disponible(self):
        cliente = ClienteFalso()
        pub = Publicador(cliente, self.cola, "box-2", lambda: {"camara_conectada": True,
                                                               "fps": 15.0},
                         lambda d: None, MetricasRegistro())
        for n in range(3):
            self.cola.encolar(payload(n))
        self.assertEqual(pub._enviar_pendientes(), 0)
        self.assertEqual(self.cola.pendientes(), 3)       # RNF-12: nada se pierde
        cliente.disponible = True
        with self.cola._conexion() as c:                   # adelantar el reloj de reintento
            c.execute("UPDATE eventos SET proximo_intento = 0")
        self.assertEqual(pub._enviar_pendientes(), 3)
        self.assertEqual(self.cola.pendientes(), 0)

    def test_tramos_cerrados_se_envian_y_se_borran(self):
        cliente = ClienteFalso()
        pub = Publicador(cliente, self.cola, "box-2", lambda: {"camara_conectada": False},
                         lambda d: None, MetricasRegistro())
        t0 = datetime(2026, 11, 9, 10, 0, tzinfo=timezone(timedelta(hours=-5)))
        pub.observacion.observando(t0)
        pub.observacion.observando(t0 + timedelta(minutes=5))
        pub.observacion.interrumpido()                     # la cámara se cae
        pub._latido()                                      # servidor caído: el tramo queda
        self.assertEqual(len(self.cola.tramos()), 1)
        cliente.disponible = True
        pub._latido()
        self.assertEqual(self.cola.tramos(), [])
        self.assertEqual(len(cliente.latidos[-1]["tramos"]), 1)


if __name__ == "__main__":
    unittest.main()

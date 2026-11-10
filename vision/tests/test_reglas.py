"""Escenarios del motor de confirmación (RF-03): entra, pasa cerca, reaparece, permanece."""
import unittest
from datetime import datetime, timedelta, timezone

from vision.configuracion import ParametrosReglas
from vision.reglas import MotorConfirmacion
from vision.tipos import GASA, Deteccion
from vision.zonas import ConjuntoZonas

ZONAS = ConjuntoZonas.desde_dict({
    "rojo": [[0.15, 0.45], [0.42, 0.45], [0.42, 0.70], [0.15, 0.70]],
    "comun": [[0.58, 0.45], [0.85, 0.45], [0.85, 0.70], [0.58, 0.70]],
})
FPS = 15
INICIO = datetime(2026, 11, 9, 10, 0, tzinfo=timezone(timedelta(hours=-5)))


def gasa(x, y, conf=0.9):
    return Deteccion(GASA, conf, x - 12, y - 9, x + 12, y + 9)


class Escenario:
    def __init__(self, **parametros):
        self.p = ParametrosReglas(**parametros)
        self.motor = MotorConfirmacion(ZONAS, self.p)
        self.t = 0.0
        self.eventos = []

    def cuadro(self, *dets):
        momento = INICIO + timedelta(seconds=self.t)
        self.eventos += self.motor.procesar(list(dets), self.t, momento)
        self.t += 1 / FPS

    def trayecto(self, desde, hasta, n):
        for i in range(n):
            a = i / max(1, n - 1)
            self.cuadro(gasa(desde[0] + (hasta[0] - desde[0]) * a,
                             desde[1] + (hasta[1] - desde[1]) * a))

    def vacio(self, segundos):
        for _ in range(int(segundos * FPS)):
            self.cuadro()

    def fin(self):
        self.eventos += self.motor.finalizar(self.t, INICIO + timedelta(seconds=self.t))
        return self.eventos


class MotorTests(unittest.TestCase):
    def test_descarte_en_el_rojo(self):
        e = Escenario()
        e.trayecto((200, 40), (180, 240), 10)   # cae hacia la boca del rojo
        e.trayecto((180, 250), (180, 280), 4)   # dentro de la zona
        e.vacio(1.0)
        self.assertEqual(e.eventos, [])          # aún no se cumple la ventana de 1,5 s
        e.vacio(1.0)
        self.assertEqual([c.zona for c in e.eventos], ["rojo"])
        rasgos = e.eventos[0].rasgos
        self.assertGreaterEqual(rasgos["fotogramas_confirmacion"], 3)
        self.assertEqual(rasgos["motivo"], "desaparicion")

    def test_descarte_en_el_comun_fecha_la_ultima_observacion(self):
        e = Escenario()
        e.trayecto((460, 40), (460, 250), 8)
        e.trayecto((460, 255), (462, 290), 5)
        momento_ultima = INICIO + timedelta(seconds=e.t - 1 / FPS)
        e.vacio(3)
        self.assertEqual(len(e.eventos), 1)
        self.assertEqual(e.eventos[0].zona, "comun")
        self.assertAlmostEqual(e.eventos[0].ocurrido_en.timestamp(), momento_ultima.timestamp(),
                               delta=0.01)

    def test_pasa_cerca_y_se_retira_no_genera_evento(self):
        e = Escenario()
        e.trayecto((460, 40), (460, 222), 8)     # se acerca
        e.cuadro(gasa(460, 230))                 # una sola observación dentro
        e.trayecto((460, 215), (600, 40), 8)     # y se va, desaparece fuera de zonas
        e.vacio(3)
        self.assertEqual(e.fin(), [])

    def test_sale_del_recipiente_y_desaparece_fuera(self):
        e = Escenario()
        e.trayecto((460, 260), (462, 290), 6)     # dentro
        e.trayecto((470, 200), (630, 20), 8)      # la sacan
        e.vacio(3)
        self.assertEqual(e.fin(), [])

    def test_reaparece_antes_de_la_ventana_un_solo_evento(self):
        e = Escenario()
        e.trayecto((460, 40), (460, 260), 8)
        e.trayecto((460, 262), (461, 280), 4)
        e.vacio(0.8)                              # oclusión breve
        e.trayecto((461, 282), (462, 290), 4)     # reaparece cerca: misma pista
        e.vacio(3)
        self.assertEqual([c.zona for c in e.fin()], ["comun"])

    def test_detecciones_duplicadas_de_la_misma_gasa(self):
        e = Escenario()
        for i in range(12):
            y = 40 + i * 22
            e.cuadro(gasa(180, y), gasa(183, y + 2))  # el detector duplica la caja
        e.vacio(3)
        self.assertLessEqual(len(e.fin()), 2)
        self.assertEqual({c.zona for c in e.eventos}, {"rojo"})

    def test_baja_confianza_se_ignora(self):
        e = Escenario(umbral_confianza=0.6)
        for i in range(12):
            e.cuadro(gasa(180, 40 + i * 22, conf=0.4))
        e.vacio(3)
        self.assertEqual(e.fin(), [])

    def test_gasa_visible_dentro_del_recipiente_cuenta_una_vez(self):
        e = Escenario(permanencia_s=2.0)
        e.trayecto((460, 40), (460, 270), 8)
        for _ in range(FPS * 20):                 # queda a la vista 20 s (sin tapa)
            e.cuadro(gasa(460, 272))
        self.assertEqual([c.zona for c in e.eventos], ["comun"])
        self.assertEqual(e.eventos[0].rasgos["motivo"], "permanencia")
        e.vacio(2.5)                              # el detector la pierde un momento
        for _ in range(FPS * 5):                  # y la vuelve a ver: es la misma gasa
            e.cuadro(gasa(461, 272))
        e.vacio(3)
        self.assertEqual(len(e.fin()), 1)

    def test_dos_descartes_seguidos_en_recipientes_distintos(self):
        e = Escenario()
        e.trayecto((200, 40), (180, 280), 12)
        e.vacio(2)
        e.trayecto((460, 40), (460, 280), 12)
        e.vacio(2)
        self.assertEqual([c.zona for c in e.fin()], ["rojo", "comun"])

    def test_cambio_de_k_en_caliente(self):
        e = Escenario(k_confirmacion=3, n_confirmacion=5)
        e.p.actualizar({"k_confirmacion": 5, "n_confirmacion": 5})
        e.trayecto((460, 40), (460, 200), 8)     # fuera de la zona
        e.trayecto((460, 255), (460, 265), 3)    # solo 3 observaciones dentro
        e.vacio(3)
        self.assertEqual(e.fin(), [])


if __name__ == "__main__":
    unittest.main()

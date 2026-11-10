"""Disparador por mano: una gasa solo cuenta si apareció junto a una mano."""
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

from vision.configuracion import Configuracion, ParametrosReglas
from vision.deteccion import DetectorMovimiento
from vision.disparador import DisparadorMano
from vision.pipeline import ServicioVision
from vision.reglas import MotorConfirmacion
from vision.tipos import GASA, MANO, Deteccion
from vision.zonas import ConjuntoZonas

ZONAS = ConjuntoZonas.desde_dict({
    "rojo": [[0.15, 0.45], [0.42, 0.45], [0.42, 0.70], [0.15, 0.70]],
    "comun": [[0.58, 0.45], [0.85, 0.45], [0.85, 0.70], [0.58, 0.70]],
})
FPS = 15
INICIO = datetime(2026, 11, 10, 10, 0, tzinfo=timezone(timedelta(hours=-5)))


def gasa(x, y, conf=0.9):
    return Deteccion(GASA, conf, x - 12, y - 9, x + 12, y + 9)


def mano(x, y, conf=0.9):
    return Deteccion(MANO, conf, x - 50, y - 40, x + 50, y + 40)


class DisparadorTests(unittest.TestCase):
    def setUp(self):
        self.d = DisparadorMano(ParametrosReglas(margen_mano=0.2))

    def test_mano_sobre_un_recipiente_activa(self):
        estado = self.d.evaluar([mano(180, 250, 0.8), gasa(180, 250)], ZONAS)
        self.assertTrue(estado.activa)
        self.assertAlmostEqual(estado.confianza, 0.8)

    def test_mano_lejos_de_los_recipientes_no_activa(self):
        self.assertFalse(self.d.evaluar([mano(320, 45)], ZONAS).activa)

    def test_mano_con_poca_confianza_no_activa(self):
        self.assertFalse(self.d.evaluar([mano(180, 250, 0.3)], ZONAS).activa)

    def test_sin_manos_no_activa(self):
        self.assertFalse(self.d.evaluar([gasa(180, 250)], ZONAS).activa)

    def test_sin_zonas_cualquier_mano_cuenta(self):
        self.assertTrue(self.d.evaluar([mano(320, 45)], ConjuntoZonas()).activa)


class Escenario:
    def __init__(self, **parametros):
        self.p = ParametrosReglas(**parametros)
        self.motor = MotorConfirmacion(ZONAS, self.p)
        self.motor.exige_mano = True
        self.t = 0.0
        self.eventos = []

    def cuadro(self, *gasas, con_mano=False):
        momento = INICIO + timedelta(seconds=self.t)
        self.eventos += self.motor.procesar(list(gasas), self.t, momento, con_mano, 0.8)
        self.t += 1 / FPS

    def descarte_al_rojo(self, con_mano):
        for i in range(10):                      # cae hacia la boca del rojo
            self.cuadro(gasa(200 - 2 * i, 40 + 22 * i), con_mano=con_mano)
        for i in range(4):                       # dentro de la zona
            self.cuadro(gasa(180, 250 + 10 * i), con_mano=con_mano)

    def vacio(self, segundos, con_mano=False):
        for _ in range(int(segundos * FPS)):
            self.cuadro(con_mano=con_mano)

    def fin(self):
        self.eventos += self.motor.finalizar(self.t, INICIO + timedelta(seconds=self.t))
        return self.eventos


class MotorConManoTests(unittest.TestCase):
    def test_descarte_con_mano_se_confirma_y_guarda_los_rasgos(self):
        e = Escenario()
        e.descarte_al_rojo(con_mano=True)
        e.vacio(2.0)
        self.assertEqual([c.zona for c in e.eventos], ["rojo"])
        rasgos = e.eventos[0].rasgos
        self.assertTrue(rasgos["mano_detectada"])
        self.assertAlmostEqual(rasgos["confianza_mano"], 0.8)

    def test_la_misma_trayectoria_sin_mano_no_genera_evento(self):
        e = Escenario()
        e.descarte_al_rojo(con_mano=False)
        e.vacio(2.0)
        self.assertEqual(e.fin(), [])
        self.assertEqual(e.motor.sin_mano, 1)

    def test_la_mano_puede_llegar_un_poco_despues_que_la_gasa(self):
        e = Escenario(gracia_mano_s=2.0)
        for i in range(5):                       # la gasa entra al cuadro antes que la mano
            e.cuadro(gasa(200 - 2 * i, 40 + 22 * i))
        for i in range(5, 10):
            e.cuadro(gasa(200 - 2 * i, 40 + 22 * i), con_mano=True)
        for i in range(4):
            e.cuadro(gasa(180, 250 + 10 * i), con_mano=True)
        e.vacio(2.0)
        self.assertEqual([c.zona for c in e.eventos], ["rojo"])

    def test_la_mano_puede_haberse_ido_justo_antes(self):
        e = Escenario(gracia_mano_s=2.0)
        e.vacio(1.0, con_mano=True)              # la mano tapa la gasa y se retira
        e.vacio(0.5)
        e.descarte_al_rojo(con_mano=False)
        e.vacio(2.0)
        self.assertEqual([c.zona for c in e.eventos], ["rojo"])

    def test_papel_que_ya_estaba_no_cuenta_aunque_luego_pase_una_mano(self):
        e = Escenario(permanencia_s=5.0, gracia_mano_s=2.0)
        for _ in range(int(4 * FPS)):            # papel blanco quieto en el común, sin mano
            e.cuadro(gasa(460, 280))
        for _ in range(int(8 * FPS)):            # una mano pasa cerca; el papel sigue ahí
            e.cuadro(gasa(460, 280), con_mano=True)
        self.assertEqual(e.fin(), [])

    def test_papel_que_reaparece_tras_taparlo_la_mano_tampoco_cuenta(self):
        e = Escenario(gracia_mano_s=2.0)
        for _ in range(int(4 * FPS)):
            e.cuadro(gasa(460, 280))
        e.vacio(2.0, con_mano=True)              # la mano lo tapa: la pista se pierde
        for _ in range(int(1 * FPS)):            # reaparece como pista nueva, con mano
            e.cuadro(gasa(462, 281), con_mano=True)
        e.vacio(2.0)
        self.assertEqual(e.fin(), [])

    def test_sin_exigir_mano_todo_sigue_como_antes(self):
        e = Escenario()
        e.motor.exige_mano = False
        e.descarte_al_rojo(con_mano=False)
        e.vacio(2.0)
        self.assertEqual([c.zona for c in e.eventos], ["rojo"])
        self.assertNotIn("mano_detectada", e.eventos[0].rasgos)


class _DetectorSinMano:
    nombre = "falso"
    umbral = 0.5
    detecta_mano = False

    def detectar(self, imagen):
        return []


class IntegracionTests(unittest.TestCase):
    def servicio(self, detector, modo):
        config = Configuracion(detector="movimiento", disparador=modo)
        return ServicioVision(config, fuente=None, detector=detector, zonas=ZONAS)

    def test_auto_se_activa_solo_si_el_detector_distingue_manos(self):
        self.assertIsNone(self.servicio(_DetectorSinMano(), "auto").disparador)
        con_mano = self.servicio(DetectorMovimiento(detectar_mano=True), "auto")
        self.assertIsNotNone(con_mano.disparador)
        self.assertTrue(con_mano.motor.exige_mano)

    def test_si_el_detector_no_distingue_manos_se_degrada_sin_fallar(self):
        s = self.servicio(_DetectorSinMano(), "si")
        self.assertIsNone(s.disparador)
        self.assertFalse(s.motor.exige_mano)

    def test_no_lo_desactiva_aunque_el_detector_distinga_manos(self):
        self.assertIsNone(self.servicio(DetectorMovimiento(detectar_mano=True), "no").disparador)

    def test_detector_de_desarrollo_encuentra_una_mano_en_movimiento(self):
        detector = DetectorMovimiento(detectar_mano=True)
        fondo = np.full((480, 640, 3), 190, np.uint8)
        for _ in range(30):
            detector.detectar(fondo)
        manos = []
        for i in range(10):
            cuadro = fondo.copy()
            x = 100 + 20 * i
            cuadro[150:260, x:x + 120] = (120, 150, 200)   # tono piel en BGR
            manos = [d for d in detector.detectar(cuadro) if d.clase == MANO]
        self.assertTrue(manos)

    def test_por_defecto_el_detector_de_desarrollo_no_emite_manos(self):
        self.assertFalse(DetectorMovimiento().detecta_mano)


if __name__ == "__main__":
    unittest.main()

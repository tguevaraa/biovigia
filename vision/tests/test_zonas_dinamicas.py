"""Zonas a partir de los tachos detectados, el detector compuesto y un descarte completo
con el tacho movido de lugar. Sin GPU ni modelos: los detectores son falsos."""
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

from vision.configuracion import Configuracion
from vision.deteccion import DetectorCompuesto, ErrorModelo, fraccion_roja
from vision.pipeline import ServicioVision
from vision.tipos import (COMUN, GASA, PERSONA, RECIPIENTE, RECIPIENTE_COMUN, RECIPIENTE_ROJO,
                          ROJO, Deteccion, Fotograma)
from vision.zonas import ConjuntoZonas
from vision.zonas_dinamicas import ZonasDinamicas


def tacho(clase, x0, y0, x1=None, y1=None, conf=0.8):
    return Deteccion(clase, conf, x0, y0, x1 if x1 is not None else x0 + 80,
                     y1 if y1 is not None else y0 + 100)


class PruebasZonasDinamicas(unittest.TestCase):
    def test_la_zona_es_la_caja_del_tacho_ampliada_hacia_arriba(self):
        zd = ZonasDinamicas(640, 480, margen_lado=0.0, margen_arriba=0.5)
        for t in range(3):
            zonas = zd.actualizar([tacho(RECIPIENTE_ROJO, 100, 300)], t * 0.1)
        z = zonas.get(ROJO)
        self.assertIsNotNone(z)
        xs = [p[0] * 640 for p in z.puntos]
        ys = [p[1] * 480 for p in z.puntos]
        self.assertAlmostEqual(min(xs), 100, delta=1)
        self.assertAlmostEqual(max(xs), 180, delta=1)
        self.assertAlmostEqual(min(ys), 250, delta=1)      # 50 px por encima de la boca
        self.assertAlmostEqual(max(ys), 400, delta=1)
        self.assertIsNone(zonas.get(COMUN))

    def test_si_mueven_el_tacho_la_zona_lo_sigue(self):
        zd = ZonasDinamicas(640, 480)
        t = 0.0
        for x in range(100, 400, 15):                      # el tacho se desliza a la derecha
            zonas = zd.actualizar([tacho(RECIPIENTE_COMUN, x, 300)], t)
            t += 0.1
        for _ in range(10):                                # y queda quieto en x = 385
            zonas = zd.actualizar([tacho(RECIPIENTE_COMUN, 385, 300)], t)
            t += 0.1
        self.assertEqual(zonas.zona_de(425 / 640, 350 / 480), COMUN)   # dónde está ahora
        self.assertIsNone(zonas.zona_de(140 / 640, 350 / 480))         # dónde estaba antes

    def test_un_fotograma_de_otro_color_no_cambia_el_tipo(self):
        zd = ZonasDinamicas(640, 480)
        for t in range(10):
            zd.actualizar([tacho(RECIPIENTE_ROJO, 100, 300)], t * 0.1)
        zonas = zd.actualizar([tacho(RECIPIENTE_COMUN, 100, 300)], 1.0)
        self.assertIsNotNone(zonas.get(ROJO))
        self.assertIsNone(zonas.get(COMUN))

    def test_si_una_mano_tapa_el_tacho_la_zona_se_mantiene(self):
        zd = ZonasDinamicas(640, 480, retener_s=3.0)
        for t in range(5):
            zd.actualizar([tacho(RECIPIENTE_ROJO, 100, 300)], t * 0.1)
        self.assertIsNotNone(zd.actualizar([], 2.0).get(ROJO))         # tapado 1,6 s
        self.assertIsNone(zd.actualizar([], 6.0).get(ROJO))            # ya no está

    def test_si_lo_mueven_mientras_se_recuerda_la_posicion_vieja_gana_la_nueva(self):
        zd = ZonasDinamicas(640, 480, retener_s=20.0)
        for t in range(5):
            zd.actualizar([tacho(RECIPIENTE_COMUN, 100, 300, conf=0.9)], t * 0.1)
        for t in range(5, 10):                       # aparece en otro lugar, con menos confianza
            zonas = zd.actualizar([tacho(RECIPIENTE_COMUN, 450, 300, conf=0.5)], t * 0.1)
        self.assertEqual(zonas.zona_de(490 / 640, 350 / 480), COMUN)
        self.assertIsNone(zonas.zona_de(140 / 640, 350 / 480))

    def test_sin_tachos_no_hay_zonas(self):
        zd = ZonasDinamicas(640, 480)
        self.assertFalse(zd.actualizar([Deteccion(GASA, 0.9, 10, 10, 20, 20)], 0.0))
        self.assertFalse(zd.alguno_visible)


class ParteFalsa:
    def __init__(self, clase, cajas):
        self.clase, self.nombre, self.cajas = clase, f"falso-{clase}", cajas

    def detectar(self, imagen, conf):
        return [Deteccion(self.clase, c, *xyxy) for xyxy, c in self.cajas]


class PruebasDetectorCompuesto(unittest.TestCase):
    def setUp(self):
        self.imagen = np.full((480, 640, 3), 200, np.uint8)        # fondo gris claro
        self.imagen[300:400, 100:180] = (30, 30, 220)               # tacho rojo (BGR)
        self.imagen[300:400, 400:480] = (40, 40, 40)                # tacho negro

    def test_el_color_decide_el_tipo_de_tacho(self):
        detector = DetectorCompuesto([
            ParteFalsa(GASA, [((150, 200, 170, 220), 0.9)]),
            ParteFalsa(RECIPIENTE, [((100, 300, 180, 400), 0.8), ((400, 300, 480, 400), 0.7)]),
            ParteFalsa(PERSONA, [((200, 50, 350, 470), 0.9)]),
        ], umbral=0.5)
        clases = sorted(d.clase for d in detector.detectar(self.imagen))
        self.assertEqual(clases, sorted([GASA, RECIPIENTE_ROJO, RECIPIENTE_COMUN, PERSONA]))

    def test_fraccion_roja(self):
        self.assertGreater(fraccion_roja(self.imagen, tacho(RECIPIENTE, 100, 300)), 0.9)
        self.assertLess(fraccion_roja(self.imagen, tacho(RECIPIENTE, 400, 300)), 0.05)

    def test_sin_modelo_de_gasas_no_arranca(self):
        with self.assertRaises(ErrorModelo):
            DetectorCompuesto([ParteFalsa(RECIPIENTE, [])], umbral=0.5)


class DetectorGuion:
    """Detector falso que devuelve, en cada fotograma, lo que diga el guion."""

    detecta_mano = False

    def __init__(self, guion):
        self.guion, self.i, self.umbral = guion, 0, 0.5

    def detectar(self, imagen):
        d = self.guion[self.i] if self.i < len(self.guion) else self.guion[-1][:1]
        self.i += 1
        return list(d)


class FuenteNula:
    conectada, fps_medido, terminada = True, 15.0, False

    def cambiar_fps(self, fps):
        pass


class PruebasDescarteConZonasDetectadas(unittest.TestCase):
    def correr(self, guion):
        config = Configuracion(detector="compuesto")
        servicio = ServicioVision(config, FuenteNula(), DetectorGuion(guion), ConjuntoZonas())
        inicio = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
        imagen = np.zeros((480, 640, 3), np.uint8)
        dt = 1 / 15
        for i in range(len(guion) + 40):                   # 40 fotogramas más: la ventana
            servicio.procesar(Fotograma(imagen, i * dt, inicio + timedelta(seconds=i * dt), i))
        return servicio.eventos

    def guion_descarte(self, x_rojo, x_comun, destino_x):
        """Tachos quietos y una gasa que baja hasta la boca del tacho elegido y desaparece."""
        tachos = [tacho(RECIPIENTE_ROJO, x_rojo, 300), tacho(RECIPIENTE_COMUN, x_comun, 300)]
        guion = [list(tachos) for _ in range(10)]
        for y in range(120, 300, 15):
            guion.append(tachos + [Deteccion(GASA, 0.9, destino_x, y, destino_x + 20, y + 20)])
        for _ in range(4):                                  # quieta en la boca
            guion.append(tachos + [Deteccion(GASA, 0.9, destino_x, 300, destino_x + 20, 320)])
        guion += [list(tachos) for _ in range(20)]          # entró: ya no se ve
        return guion

    def test_descarte_en_el_rojo(self):
        eventos = self.correr(self.guion_descarte(100, 400, 130))
        self.assertEqual([e.recipiente for e in eventos], [ROJO])

    def test_con_los_tachos_intercambiados_de_lugar_cambia_el_veredicto(self):
        # Misma gasa, mismo lugar; pero ahora en x = 100 está el común: no hay polígono fijo.
        eventos = self.correr(self.guion_descarte(400, 100, 130))
        self.assertEqual([e.recipiente for e in eventos], [COMUN])

    def test_sin_tachos_a_la_vista_no_hay_evento(self):
        guion = [[Deteccion(GASA, 0.9, 130, y, 150, y + 20)] for y in range(120, 300, 15)]
        guion += [[] for _ in range(20)]
        self.assertEqual(self.correr(guion), [])


if __name__ == "__main__":
    unittest.main()

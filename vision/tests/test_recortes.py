"""Pruebas de la búsqueda en recortes (etapa 2), con un detector falso."""
import unittest

import numpy as np

from vision.recortes import buscar_en_recortes, fusionar_regiones, region_de_busqueda
from vision.tipos import Deteccion


def persona(x0, y0, x1, y1):
    return Deteccion("persona", 0.9, x0, y0, x1, y1)


class DetectorDeBlanco:
    """Encuentra el bloque blanco de la imagen que recibe; anota los tamaños recibidos."""

    def __init__(self):
        self.recibidos = []

    def __call__(self, recorte):
        self.recibidos.append(recorte.shape[:2])
        ys, xs = np.nonzero(recorte[:, :, 0] == 255)
        if not len(xs):
            return []
        return [Deteccion("gasa", 0.8, float(xs.min()), float(ys.min()),
                          float(xs.max() + 1), float(ys.max() + 1))]


class PruebasRecortes(unittest.TestCase):
    def setUp(self):
        self.original = np.zeros((1080, 1920, 3), np.uint8)
        self.original[500:530, 1500:1530] = 255          # gasa de 30 × 30 px

    def test_la_caja_vuelve_a_coordenadas_del_original(self):
        det = DetectorDeBlanco()
        gasas = buscar_en_recortes(self.original, [persona(1400, 300, 1650, 1000)], det)
        self.assertEqual(len(gasas), 1)
        g = gasas[0]
        self.assertEqual((g.x0, g.y0, g.x1, g.y1), (1500, 500, 1530, 530))

    def test_solo_se_analiza_la_zona_de_la_persona(self):
        det = DetectorDeBlanco()
        buscar_en_recortes(self.original, [persona(1400, 300, 1650, 1000)], det)
        alto, ancho = det.recibidos[0]
        self.assertLess(ancho, 1920 / 3)                  # la gasa queda ~3 veces más grande

    def test_sin_guias_no_busca(self):
        det = DetectorDeBlanco()
        self.assertEqual(buscar_en_recortes(self.original, [], det), [])
        self.assertEqual(det.recibidos, [])

    def test_regiones_solapadas_se_analizan_una_vez(self):
        det = DetectorDeBlanco()
        gasas = buscar_en_recortes(self.original, [persona(1400, 300, 1650, 1000),
                                                   persona(1450, 350, 1700, 1000)], det)
        self.assertEqual(len(det.recibidos), 1)
        self.assertEqual(len(gasas), 1)

    def test_region_minima_y_dentro_de_la_imagen(self):
        x0, y0, x1, y1 = region_de_busqueda(Deteccion("recipiente", 1, 1900, 1070, 1910, 1075),
                                            1920, 1080, lado_min=320)
        self.assertTrue(0 <= x0 < x1 <= 1920 and 0 <= y0 < y1 <= 1080)
        self.assertGreaterEqual(x1 - x0, 160)             # recortado por el borde, no diminuto

    def test_fusionar_regiones(self):
        self.assertEqual(fusionar_regiones([(0, 0, 10, 10), (5, 5, 20, 20), (50, 50, 60, 60)]),
                         [(0, 0, 20, 20), (50, 50, 60, 60)])


if __name__ == "__main__":
    unittest.main()

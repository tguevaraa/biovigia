"""Pruebas de la reducción sin deformar y del paso de cajas al original."""
import unittest
from datetime import datetime, timezone

import numpy as np

from vision.captura import a_fotograma, encuadrar, normalizar

AHORA = datetime(2026, 11, 20, tzinfo=timezone.utc)


class PruebasEncuadre(unittest.TestCase):
    def test_telefono_16_9_queda_con_bandas_y_sin_deformar(self):
        imagen = np.full((1080, 1920, 3), 200, dtype=np.uint8)
        reducida, escala, dx, dy = encuadrar(imagen, 640, 480)
        self.assertEqual(reducida.shape, (480, 640, 3))
        self.assertAlmostEqual(escala, 1 / 3)
        self.assertEqual((dx, dy), (0, 60))
        # Bandas negras arriba y abajo; contenido en el medio.
        self.assertEqual(int(reducida[:60].max()), 0)
        self.assertEqual(int(reducida[420:].max()), 0)
        self.assertEqual(int(reducida[60:420].min()), 200)

    def test_un_circulo_sigue_siendo_circulo(self):
        imagen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        imagen[440:640, 860:1060] = 255  # cuadrado de 200 × 200
        reducida = normalizar(imagen, 640, 480)
        filas, columnas = np.nonzero(reducida[:, :, 0] > 127)
        alto, ancho = filas.max() - filas.min() + 1, columnas.max() - columnas.min() + 1
        self.assertLessEqual(abs(int(alto) - int(ancho)), 1)

    def test_camara_4_3_no_cambia(self):
        imagen = np.zeros((480, 640, 3), dtype=np.uint8)
        reducida, escala, dx, dy = encuadrar(imagen, 640, 480)
        self.assertIs(reducida, imagen)
        self.assertEqual((escala, dx, dy), (1.0, 0, 0))

    def test_gris_se_convierte_a_color(self):
        self.assertEqual(normalizar(np.zeros((720, 1280), np.uint8), 640, 480).shape,
                         (480, 640, 3))


class PruebasCajaEnOriginal(unittest.TestCase):
    def test_caja_vuelve_a_pixeles_del_telefono(self):
        imagen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        f = a_fotograma(imagen, 640, 480, 0.0, AHORA, 1)
        self.assertIs(f.original, imagen)
        # Un objeto en (100, 160)–(120, 180) del fotograma reducido (banda de 60 px arriba).
        self.assertEqual(f.caja_en_original(100, 160, 120, 180), (300, 300, 360, 360))

    def test_caja_en_la_banda_se_recorta_al_borde(self):
        f = a_fotograma(np.zeros((1080, 1920, 3), np.uint8), 640, 480, 0.0, AHORA, 1)
        self.assertEqual(f.caja_en_original(0, 0, 640, 480), (0, 0, 1920, 1080))

    def test_sin_original_devuelve_la_misma_caja(self):
        from vision.tipos import Fotograma
        f = Fotograma(np.zeros((480, 640, 3), np.uint8), 0.0, AHORA)
        self.assertEqual(f.caja_en_original(10, 20, 30, 40), (10, 20, 30, 40))


if __name__ == "__main__":
    unittest.main()

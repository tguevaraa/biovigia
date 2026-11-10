import tempfile
import unittest
from pathlib import Path

from vision.zonas import ConjuntoZonas, Zona

CUADRADO = ((0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4))


class ZonaTests(unittest.TestCase):
    def test_contencion(self):
        z = Zona("rojo", CUADRADO)
        self.assertTrue(z.contiene(0.2, 0.2))
        self.assertFalse(z.contiene(0.5, 0.2))
        self.assertFalse(z.contiene(0.05, 0.05))

    def test_poligono_concavo(self):
        z = Zona("comun", ((0, 0), (1, 0), (1, 1), (0.5, 0.4), (0, 1)))
        self.assertTrue(z.contiene(0.2, 0.3))
        self.assertFalse(z.contiene(0.5, 0.8))

    def test_validaciones(self):
        with self.assertRaises(ValueError):
            Zona("azul", CUADRADO)
        with self.assertRaises(ValueError):
            Zona("rojo", ((0, 0), (1, 1)))

    def test_caja_en_pixeles_con_margen(self):
        x0, y0, x1, y1 = Zona("rojo", CUADRADO).caja_px(640, 480, margen=0.0)
        self.assertEqual((x0, y0, x1, y1), (64, 48, 256, 192))

    def test_conjunto_ida_y_vuelta(self):
        conjunto = ConjuntoZonas.desde_dict({"rojo": [list(p) for p in CUADRADO], "comun": None})
        self.assertEqual(conjunto.zona_de(0.2, 0.2), "rojo")
        self.assertIsNone(conjunto.zona_de(0.9, 0.9))
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "zonas.json"
            conjunto.guardar(ruta, "box-2")
            cargado = ConjuntoZonas.cargar(ruta)
        self.assertEqual(cargado.como_dict(), conjunto.como_dict())
        self.assertFalse(cargado.completas)

    def test_zona_mas_especifica_gana(self):
        grande = [[0, 0], [1, 0], [1, 1], [0, 1]]
        conjunto = ConjuntoZonas.desde_dict({"comun": grande, "rojo": [list(p) for p in CUADRADO]})
        self.assertEqual(conjunto.zona_de(0.2, 0.2), "rojo")
        self.assertEqual(conjunto.zona_de(0.8, 0.8), "comun")


if __name__ == "__main__":
    unittest.main()

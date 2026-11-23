"""Pruebas del estabilizador de cajas: histéresis, retención, suavizado y falsos positivos."""
import unittest

from vision.estabilizador import Estabilizador, iou, quitar_contenidas
from vision.tipos import Deteccion

R = "recipiente"


def caja(conf: float, x: float = 100, y: float = 100, lado: float = 80,
         clase: str = R) -> Deteccion:
    return Deteccion(clase, conf, x, y, x + lado, y + lado)


class PruebasEstabilizador(unittest.TestCase):
    def setUp(self):
        self.e = Estabilizador(umbral_alta=0.35, umbral_baja=0.15, retener_s=1.0,
                               alfa=0.5, min_vistas=2)

    def test_no_parpadea_con_confianza_cerca_del_umbral(self):
        # 0,40 lo crea; luego oscila por debajo de 0,35 pero encima de 0,15: no se pierde.
        confianzas = [0.40, 0.38, 0.30, 0.36, 0.28, 0.33, 0.31, 0.29]
        visibles = [len(self.e.actualizar([caja(c)], t / 15)) for t, c in enumerate(confianzas)]
        self.assertEqual(visibles[0], 0)          # aún no confirmado (min_vistas = 2)
        self.assertEqual(visibles[1:], [1] * 7)   # visible sin parpadear

    def test_un_objeto_nuevo_necesita_confianza_alta(self):
        for t in range(5):
            self.assertEqual(self.e.actualizar([caja(0.30)], t / 15), [])

    def test_retiene_la_caja_si_una_mano_lo_tapa(self):
        self.e.actualizar([caja(0.9)], 0.0)
        self.e.actualizar([caja(0.9)], 0.1)
        visibles = self.e.actualizar([], 0.8)     # tapado 0,7 s: sigue
        self.assertEqual(len(visibles), 1)
        self.assertTrue(visibles[0].retenido(0.8))
        self.assertEqual(self.e.actualizar([], 1.2), [])  # 1,1 s sin verlo: perdido

    def test_suaviza_un_salto_de_la_caja(self):
        self.e.actualizar([caja(0.9, x=100)], 0.0)
        o = self.e.actualizar([caja(0.9, x=120)], 0.1)[0]
        self.assertAlmostEqual(o.caja.x0, 110)    # alfa 0,5: a mitad de camino
        self.assertEqual(o.id, 1)                 # mismo objeto, mismo identificador

    def test_dos_tachos_se_siguen_por_separado(self):
        for t in (0.0, 0.1):
            visibles = self.e.actualizar([caja(0.9, x=0), caja(0.5, x=300)], t)
        self.assertEqual(sorted(o.id for o in visibles), [1, 2])

    def test_falso_positivo_de_un_fotograma_no_se_publica(self):
        self.e.actualizar([caja(0.9, x=0)], 0.0)
        self.e.actualizar([caja(0.9, x=0)], 0.1)
        visibles = self.e.actualizar([caja(0.9, x=0), caja(0.8, x=400)], 0.2)
        self.assertEqual(len(visibles), 1)

    def test_no_mezcla_clases_distintas(self):
        self.e.actualizar([caja(0.9)], 0.0)
        visibles = self.e.actualizar([caja(0.9, clase="persona")], 0.1)
        self.assertEqual(visibles, [])            # la persona es otro objeto, aún sin confirmar

    def test_iou(self):
        self.assertAlmostEqual(iou(caja(1), caja(1)), 1.0)
        self.assertEqual(iou(caja(1, x=0), caja(1, x=500)), 0.0)

    def test_medio_cuerpo_dentro_del_cuerpo_entero_es_una_sola_persona(self):
        entero = Deteccion("persona", 0.87, 680, 325, 960, 705)
        medio = Deteccion("persona", 0.40, 760, 325, 960, 575)
        est = Estabilizador()
        for t in range(3):
            visibles = est.actualizar([entero, medio], t / 10)
        self.assertEqual(len(visibles), 1)
        self.assertEqual(quitar_contenidas([medio, entero]), [entero])

    def test_dos_personas_separadas_se_mantienen(self):
        a = Deteccion("persona", 0.9, 200, 180, 575, 710)
        b = Deteccion("persona", 0.8, 680, 325, 960, 705)
        self.assertEqual(len(quitar_contenidas([a, b])), 2)


if __name__ == "__main__":
    unittest.main()

"""Extremo a extremo sin cámara: video sintético → detector de desarrollo → eventos."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from vision.captura import FuenteArchivo
from vision.configuracion import Configuracion
from vision.deteccion import DetectorMovimiento
from vision.pipeline import ServicioVision
from vision.zonas import ConjuntoZonas

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "generar_video_sintetico", RAIZ / "herramientas" / "generar_video_sintetico.py")
sintetico = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sintetico)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.videos = {}
        for i, tipo in enumerate(("rojo", "comun", "negativo", "vacio")):
            ruta = Path(cls.tmp.name) / f"{tipo}.mp4"
            sintetico.generar(tipo, ruta, semilla=i)
            cls.videos[tipo] = ruta

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def correr(self, tipo):
        config = Configuracion(detector="movimiento")
        config.archivo_zonas = Path(self.tmp.name) / "zonas.json"
        fuente = FuenteArchivo(str(self.videos[tipo]), 640, 480, 15)
        servicio = ServicioVision(config, fuente, DetectorMovimiento(),
                                  ConjuntoZonas.desde_dict(sintetico.zonas()))
        try:
            return servicio.ejecutar()
        finally:
            fuente.cerrar()

    def test_descarte_al_rojo_es_conforme_y_sin_evidencia(self):
        eventos = self.correr("rojo")
        self.assertEqual([e.recipiente for e in eventos], ["rojo"])
        self.assertEqual(eventos[0].veredicto, "conforme")
        self.assertIsNone(eventos[0].evidencia_jpeg)

    def test_descarte_al_comun_lleva_recorte_jpeg(self):
        eventos = self.correr("comun")
        self.assertEqual([e.veredicto for e in eventos], ["no_conforme"])
        jpeg = eventos[0].evidencia_jpeg
        self.assertTrue(jpeg and jpeg[:2] == b"\xff\xd8")
        cuerpo = eventos[0].como_payload()
        self.assertTrue(cuerpo["id_externo"].startswith("box2-"))
        self.assertRegex(cuerpo["ocurrido_en"], r"[+-]\d\d:\d\d$")

    def test_recorte_es_solo_la_zona(self):
        import cv2
        import numpy as np

        eventos = self.correr("comun")
        img = cv2.imdecode(np.frombuffer(eventos[0].evidencia_jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertLess(img.shape[0] * img.shape[1], 640 * 480 * 0.2)

    def test_negativo_y_escena_vacia_no_generan_eventos(self):
        self.assertEqual(self.correr("negativo"), [])
        self.assertEqual(self.correr("vacio"), [])


if __name__ == "__main__":
    unittest.main()

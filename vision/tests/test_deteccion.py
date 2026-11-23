"""Pruebas de ErrorModelo: motivo, ruta y mensaje de cada caso."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from vision.deteccion import DetectorYOLO, ErrorModelo


class PruebasErrorModelo(unittest.TestCase):
    def test_modelo_inexistente(self):
        ruta = Path("vision/modelos/no-existe.pt")
        with self.assertRaises(ErrorModelo) as ctx:
            DetectorYOLO(ruta, umbral=0.5)
        self.assertEqual(ctx.exception.motivo, ErrorModelo.NO_EXISTE)
        self.assertEqual(ctx.exception.ruta, ruta)
        self.assertIn("--detector movimiento", str(ctx.exception))

    def test_modelo_sin_clase_gasa(self):
        falso = types.ModuleType("ultralytics")
        falso.YOLO = lambda _ruta: types.SimpleNamespace(names={0: "person", 1: "car"})
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "yolov8n.pt"
            ruta.write_bytes(b"")
            with mock.patch.dict(sys.modules, {"ultralytics": falso}):
                with self.assertRaises(ErrorModelo) as ctx:
                    DetectorYOLO(ruta, umbral=0.5)
        self.assertEqual(ctx.exception.motivo, ErrorModelo.SIN_CLASE_GASA)
        self.assertIn("person, car", str(ctx.exception))

    def test_sin_ultralytics(self):
        error = ErrorModelo.sin_ultralytics(Path("m.pt"))
        self.assertEqual(error.motivo, ErrorModelo.SIN_ULTRALYTICS)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("pip install", str(error))


if __name__ == "__main__":
    unittest.main()

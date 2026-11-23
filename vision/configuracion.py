"""Configuración del servicio de visión: variables de entorno (``vision/.env``) y CLI.

Los parámetros de operación (umbral, ventana, k-de-N, fps) llegan además desde el
servidor cada 30 s y se aplican en caliente, sin reiniciar (RNF-16). Los valores de
aquí son los que se usan mientras el servidor no responde.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_VISION = Path(__file__).resolve().parent
RAIZ_PROYECTO = RAIZ_VISION.parent


def _cargar_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv es opcional
        return
    load_dotenv(RAIZ_VISION / ".env")


def _bool(valor: str | None, defecto: bool = False) -> bool:
    if valor is None or valor == "":
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _env(nombre: str, defecto: str = "") -> str:
    return os.environ.get(f"BIOVIGIA_{nombre}", defecto)


@dataclass
class ParametrosReglas:
    """Parámetros de M2/M3 que el administrador ajusta desde PAN-10."""

    umbral_confianza: float = 0.50
    ventana_confirmacion_s: float = 1.5
    k_confirmacion: int = 3
    n_confirmacion: int = 5
    fps_muestreo: int = 15
    # Si la gasa queda visible y quieta dentro de la zona este tiempo, también se confirma
    # (recipientes sin tapa). Debe ser mayor que la duda de una mano sobre la boca. 0 = no.
    permanencia_s: float = 5.0
    # Memoria de objetos ya contados: evita contar dos veces una gasa que sigue a la vista.
    memoria_s: float = 60.0
    radio_memoria: float = 0.06  # fracción del ancho del fotograma
    # Una gasa que se movió menos que esto (fracción del ancho) en toda su trayectoria ya
    # estaba dentro del recipiente: no es un descarte nuevo.
    desplazamiento_min: float = 0.08
    # Disparador por mano (docs/deteccion-dos-etapas.md). Una gasa solo puede confirmarse
    # si hubo una mano cerca de los recipientes como mucho este tiempo antes o después
    # de que apareciera.
    gracia_mano_s: float = 2.0
    # Cuánto se amplía la caja de cada zona para formar el área de aproximación (1.0 =
    # el ancho y el alto de la zona, hacia cada lado).
    margen_mano: float = 1.0

    def actualizar(self, valores: dict) -> list[str]:
        cambios = []
        for campo in ("umbral_confianza", "ventana_confirmacion_s", "k_confirmacion",
                      "n_confirmacion", "fps_muestreo"):
            if campo in valores and valores[campo] is not None:
                tipo = type(getattr(self, campo))
                nuevo = tipo(valores[campo])
                if nuevo != getattr(self, campo):
                    setattr(self, campo, nuevo)
                    cambios.append(f"{campo}={nuevo}")
        return cambios


@dataclass
class Configuracion:
    servidor: str = "http://localhost:8000"
    token: str = ""
    box: str = "box-2"
    fuente: str = "0"
    # compuesto: un modelo por objeto (gasas, tachos, personas) · yolo: un solo modelo con
    # todas las clases · movimiento: detector de desarrollo sin modelo.
    detector: str = "compuesto"
    # auto: se activa si el modelo tiene la clase «mano» · si: lo exige (con el detector
    # de desarrollo usa una mano aproximada por color de piel) · no: desactivado.
    disparador: str = "auto"
    modelo: Path = RAIZ_VISION / "modelos" / "biovigia-gasa-v0.1.pt"
    nombre_modelo: str = ""
    # Detector compuesto (docs/entrenar-modelos.md): cada modelo reconoce un solo objeto.
    modelo_gasas: Path = RAIZ_VISION / "modelos" / "biovigia-gasas-v0.5.pt"
    modelo_tachos: Path | None = RAIZ_VISION / "modelos" / "biovigia-tachos-v0.2.pt"
    modelo_personas: Path | None = RAIZ_VISION / "modelos" / "yolo11n-coco.pt"
    # Fracción de la caja de un tacho que debe ser roja para llamarlo «rojo».
    umbral_rojo: float = 0.25
    # detectadas: las zonas salen de los tachos que el modelo ve en cada fotograma (siguen
    # al tacho si lo mueven) · fijas: polígonos de PAN-09 o vision/zonas.json (solo para
    # el detector de desarrollo, que no reconoce tachos).
    zonas: str = "detectadas"
    imgsz: int = 640
    # Tamaño de trabajo: el detector, las reglas y las zonas usan este fotograma reducido.
    ancho: int = 640
    alto: int = 480
    # Resolución que se le pide a la cámara. 0 = no pedir nada y usar la nativa (un
    # teléfono con Iriun o DroidCam entrega 1920 × 1080). El original se conserva en el
    # Fotograma para buscar objetos pequeños en recortes de alta resolución.
    captura_ancho: int = 0
    captura_alto: int = 0
    archivo_zonas: Path = RAIZ_VISION / "zonas.json"
    dir_cola: Path = RAIZ_VISION / "cola"
    clasificador: Path | None = None
    evidencia_conformes: bool = False
    mostrar: bool = False
    verificar_tls: str = "true"
    intervalo_latido_s: float = 10.0
    intervalo_config_s: float = 30.0
    cloudwatch: bool = False
    cloudwatch_region: str = "us-east-1"
    parametros: ParametrosReglas = field(default_factory=ParametrosReglas)

    @property
    def etiqueta_modelo(self) -> str:
        if self.nombre_modelo:
            return self.nombre_modelo[:40]
        if self.detector == "movimiento":
            return "dev-movimiento-v0"
        if self.detector == "compuesto":
            partes = [self.modelo_gasas, self.modelo_tachos]
            return "+".join(Path(p).stem.removeprefix("biovigia-") for p in partes if p)[:40]
        return Path(self.modelo).stem[:40]

    @property
    def verify(self):
        """Valor para ``requests``: True, False o la ruta a un certificado de CA (RNF-18)."""
        valor = self.verificar_tls.strip()
        if valor.lower() in {"false", "0", "no"}:
            return False
        if valor.lower() in {"true", "1", "si", "sí", "yes", ""}:
            return True
        return valor

    @property
    def zonas_detectadas(self) -> bool:
        """Las zonas salen de los tachos detectados. El detector de movimiento no reconoce
        tachos, así que con él siempre se usan las zonas fijas."""
        return self.zonas != "fijas" and self.detector != "movimiento"

    @property
    def modelos_compuesto(self) -> dict:
        return {"gasas": self.modelo_gasas, "tachos": self.modelo_tachos,
                "personas": self.modelo_personas, "umbral_rojo": self.umbral_rojo}

    @property
    def es_archivo(self) -> bool:
        return not self.fuente.isdigit() and "://" not in self.fuente


def desde_entorno() -> Configuracion:
    _cargar_env()
    c = Configuracion()
    c.servidor = _env("SERVIDOR", c.servidor).rstrip("/")
    c.token = _env("TOKEN", c.token)
    c.box = _env("BOX", c.box)
    c.fuente = _env("FUENTE", c.fuente)
    c.detector = _env("DETECTOR", c.detector)
    c.disparador = _env("DISPARADOR", c.disparador).strip().lower() or "auto"
    if _env("MODELO"):
        c.modelo = _ruta(_env("MODELO"))
    c.nombre_modelo = _env("NOMBRE_MODELO", "")
    if _env("MODELO_GASAS"):
        c.modelo_gasas = _ruta(_env("MODELO_GASAS"))
    # Tachos y personas: si la variable existe pero está vacía, ese modelo no se usa.
    for nombre in ("tachos", "personas"):
        if f"BIOVIGIA_MODELO_{nombre.upper()}" in os.environ:
            valor = _env(f"MODELO_{nombre.upper()}")
            setattr(c, f"modelo_{nombre}", _ruta(valor) if valor else None)
    c.umbral_rojo = float(_env("UMBRAL_ROJO", str(c.umbral_rojo)))
    c.zonas = (_env("MODO_ZONAS", c.zonas).strip().lower() or "detectadas")
    c.imgsz = int(_env("IMGSZ", str(c.imgsz)))
    c.captura_ancho = int(_env("CAPTURA_ANCHO", str(c.captura_ancho)) or 0)
    c.captura_alto = int(_env("CAPTURA_ALTO", str(c.captura_alto)) or 0)
    if _env("ZONAS"):
        c.archivo_zonas = _ruta(_env("ZONAS"))
    if _env("DIR_COLA"):
        c.dir_cola = _ruta(_env("DIR_COLA"))
    if _env("CLASIFICADOR"):
        c.clasificador = _ruta(_env("CLASIFICADOR"))
    c.evidencia_conformes = _bool(_env("EVIDENCIA_CONFORMES"), False)
    c.verificar_tls = _env("VERIFICAR_TLS", c.verificar_tls)
    c.cloudwatch = _bool(_env("CLOUDWATCH"), False)
    c.cloudwatch_region = _env("CLOUDWATCH_REGION", c.cloudwatch_region)
    p = c.parametros
    p.umbral_confianza = float(_env("UMBRAL_CONFIANZA", str(p.umbral_confianza)))
    p.ventana_confirmacion_s = float(_env("VENTANA_S", str(p.ventana_confirmacion_s)))
    p.k_confirmacion = int(_env("K", str(p.k_confirmacion)))
    p.n_confirmacion = int(_env("N", str(p.n_confirmacion)))
    p.fps_muestreo = int(_env("FPS", str(p.fps_muestreo)))
    p.permanencia_s = float(_env("PERMANENCIA_S", str(p.permanencia_s)))
    p.gracia_mano_s = float(_env("GRACIA_MANO_S", str(p.gracia_mano_s)))
    p.margen_mano = float(_env("MARGEN_MANO", str(p.margen_mano)))
    return c


def _ruta(valor: str) -> Path:
    ruta = Path(valor)
    return ruta if ruta.is_absolute() else (RAIZ_PROYECTO / ruta).resolve()


def argumentos() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m vision",
        description="Servicio de visión de BioVigIA: verifica en qué recipiente se descarta "
                    "la gasa y publica cada evento en el servidor.")
    ap.add_argument("--fuente", help="Índice de la cámara (0), ruta de un video o URL rtsp://")
    ap.add_argument("--detector", choices=["compuesto", "yolo", "movimiento"],
                    help="compuesto: un modelo por objeto (gasas, tachos, personas). yolo: un "
                         "solo modelo entrenado. movimiento: detector de desarrollo sin modelo")
    ap.add_argument("--zonas", choices=["detectadas", "fijas"],
                    help="detectadas: las zonas siguen a los tachos que ve el modelo. fijas: "
                         "polígonos de PAN-09 (solo para el detector de desarrollo)")
    ap.add_argument("--disparador", choices=["auto", "si", "no"],
                    help="Disparador por mano: auto (si el modelo tiene la clase mano), "
                         "si (obligatorio) o no")
    ap.add_argument("--modelo", help="Ruta a los pesos .pt u .onnx")
    ap.add_argument("--box", help="Código del puesto (por defecto box-2)")
    ap.add_argument("--servidor", help="URL del servidor, p. ej. http://localhost:8000")
    ap.add_argument("--mostrar", action="store_true",
                    help="Abre una ventana con el video, las zonas y las detecciones")
    ap.add_argument("--sin-servidor", action="store_true",
                    help="No publica: muestra los eventos en consola (pruebas sin servidor)")
    ap.add_argument("--enviar-referencia", action="store_true",
                    help="Envía al servidor un fotograma de la escena vacía para trazar zonas")
    ap.add_argument("--listar-camaras", action="store_true",
                    help="Muestra qué índices de cámara (0, 1, 2…) entregan imagen y sale")
    ap.add_argument("--editar-zonas", action="store_true",
                    help="Abre el editor local de zonas (guarda vision/zonas.json)")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap


def aplicar_argumentos(c: Configuracion, args: argparse.Namespace) -> Configuracion:
    if args.fuente is not None:
        c.fuente = args.fuente
    if args.detector:
        c.detector = args.detector
    if getattr(args, "zonas", None):
        c.zonas = args.zonas
    if getattr(args, "disparador", None):
        c.disparador = args.disparador
    if args.modelo:
        c.modelo = _ruta(args.modelo)
    if args.box:
        c.box = args.box
    if args.servidor:
        c.servidor = args.servidor.rstrip("/")
    if args.mostrar:
        c.mostrar = True
    return c

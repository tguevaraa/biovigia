"""Servicio de visión de BioVigIA (componente C1, módulos M1 a M3 y recorte de M4).

Canalización por etapas: captura → detección → confirmación → publicación. Ninguna etapa
devuelve datos hacia atrás y ningún fotograma sale de este proceso: solo salen eventos
confirmados con el recorte de la zona del recipiente (RNF-02, RNF-03).
"""

import os

# OpenCV imprime mucho ruido al buscar cámaras (DSHOW, obsensor…). El servicio informa los
# problemas con sus propios mensajes, así que se silencian antes de importar cv2.
os.environ.setdefault("OPENCV_LOG_LEVEL", "FATAL")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")

__version__ = "0.1.0"

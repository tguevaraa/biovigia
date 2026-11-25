"""Canalización por etapas del servicio de visión (sección 9.2 del informe).

captura (M1) → detección (M2) → confirmación (M3) → evidencia y publicación (M4).
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import cv2
import numpy as np

from .captura import FuenteVideo
from .cola import ColaLocal
from .configuracion import Configuracion
from .deteccion import Detector
from .disparador import SIN_MANO, DisparadorMano
from .estabilizador import quitar_contenidas
from .evidencia import a_jpeg, recortar
from .publicador import Publicador
from .reglas import Confirmado, MotorConfirmacion, ReglaConClasificador, ReglaKdeN
from .tipos import (
    COMUN,
    GASA,
    MANO,
    PERSONA,
    RECIPIENTE_COMUN,
    RECIPIENTE_ROJO,
    ROJO,
    Deteccion,
    EventoDescarte,
    Fotograma,
    id_externo_para,
)
from .zonas import ConjuntoZonas
from .zonas_dinamicas import ZonasDinamicas

log = logging.getLogger("vision.pipeline")


def es_el_tacho(d: Deteccion, tachos: list[Deteccion]) -> bool:
    """Un «residuo» que cubre casi todo un tacho es el tacho mismo (la jeringa-v0.8 marcaba
    el tacho rojo entero como jeringa). Un residuo de verdad es mucho más chico que el tacho."""
    area = max((d.x1 - d.x0) * (d.y1 - d.y0), 1e-6)
    for t in tachos:
        ix = max(0.0, min(d.x1, t.x1) - max(d.x0, t.x0))
        iy = max(0.0, min(d.y1, t.y1) - max(d.y0, t.y0))
        if ix * iy > 0.5 * area and area > 0.4 * (t.x1 - t.x0) * (t.y1 - t.y0):
            return True
    return False

COLOR_ZONA = {ROJO: (40, 40, 220), COMUN: (230, 230, 230)}
NOMBRE_ZONA = {ROJO: "Recipiente rojo", COMUN: "Recipiente comun"}
VENTANA_PREVIA = "BioVigIA - vista previa (no se graba)"
# Vista obstruida: sin ningún tacho a la vista este tiempo, o la imagen tapada (oscura o
# sin textura), el proceso no se registra: el lapso queda como no observado y no se
# confirman descartes (una mano que tapa el tacho «hace desaparecer» la gasa).
OBSTRUCCION_S = 2.0
CONFIANZA_TACHO_VISTO = 0.15
UMBRAL_DIBUJO = 0.35  # personas y tachos en la vista previa


class ServicioVision:
    def __init__(self, config: Configuracion, fuente: FuenteVideo, detector: Detector,
                 zonas: ConjuntoZonas, cola: Optional[ColaLocal] = None,
                 publicador: Optional[Publicador] = None,
                 al_confirmar: Optional[Callable[[EventoDescarte], None]] = None) -> None:
        self.config = config
        self.fuente = fuente
        self.detector = detector
        # Lo que las reglas siguen como residuo: la gasa y, con el detector compuesto, los
        # objetos extra (tubos, jeringas…).
        self.residuos = set(getattr(detector, "residuos", (GASA,)))
        self._ventana_lista = False
        self.cola = cola
        self.publicador = publicador
        self.al_confirmar = al_confirmar
        regla = (ReglaConClasificador(config.clasificador) if config.clasificador
                 else ReglaKdeN())
        self.motor = MotorConfirmacion(zonas, config.parametros, regla, config.ancho,
                                       config.alto)
        # Zonas detectadas: salen de los tachos que el modelo ve en cada fotograma, así
        # siguen al tacho si lo mueven. Las zonas fijas quedan para el detector de desarrollo.
        self.zonas_dinamicas = (ZonasDinamicas(config.ancho, config.alto,
                                               margen_arriba=config.margen_zona)
                                if config.zonas_detectadas else None)
        self._ultimo_tacho_t: Optional[float] = None
        self.obstruida = False
        self._despejada_desde: Optional[float] = None
        self.motivo_obstruccion = ""
        self.no_registrados = 0
        self.disparador = self._crear_disparador()
        self.motor.exige_mano = self.disparador is not None
        self._mano = SIN_MANO
        self._recortes: dict[str, np.ndarray] = {}
        self._zonas_alineadas: Optional[bool] = None
        self._detener = threading.Event()
        self.eventos: list[EventoDescarte] = []
        self._ultimo: Optional[Fotograma] = None
        self._aviso_sin_zonas = False

    def _crear_disparador(self) -> Optional[DisparadorMano]:
        """Disparador por mano, según ``config.disparador`` y lo que distinga el detector."""
        modo = self.config.disparador
        if modo == "no":
            return None
        if not getattr(self.detector, "detecta_mano", False):
            if modo == "si":
                log.warning("Se pidió el disparador por mano, pero el detector %s no distingue "
                            "manos: se desactiva y se confirma solo con las reglas.",
                            self.config.etiqueta_modelo)
            return None
        log.info("Disparador por mano activo (gracia %.1f s, margen %.1f)",
                 self.config.parametros.gracia_mano_s, self.config.parametros.margen_mano)
        return DisparadorMano(self.config.parametros, self.config.ancho, self.config.alto)

    # --- estado y configuración en caliente -----------------------------------------------------

    @property
    def zonas(self) -> ConjuntoZonas:
        return self.motor.zonas

    def estado(self) -> dict:
        return {
            "camara_conectada": self.fuente.conectada,
            "fps": round(self.fuente.fps_medido, 1) if self.fuente.fps_medido else None,
            "zonas_alineadas": self._zonas_alineadas,
            "modelo": self.config.etiqueta_modelo,
            "disparador_mano": self.disparador is not None,
        }

    def aplicar_configuracion(self, datos: dict) -> None:
        """Parámetros y zonas que llegan del servidor (PAN-09 y PAN-10)."""
        cambios = self.config.parametros.actualizar(datos.get("parametros") or {})
        if cambios:
            self.detector.umbral = self.config.parametros.umbral_confianza
            self.fuente.cambiar_fps(self.config.parametros.fps_muestreo)
            log.info("Parámetros actualizados desde el servidor: %s", ", ".join(cambios))
        if self.zonas_dinamicas is not None:
            return  # las zonas salen de los tachos detectados, no de PAN-09
        remotas = ConjuntoZonas.desde_dict(datos.get("zonas") or {})
        if remotas and remotas.como_dict() != self.motor.zonas.como_dict():
            self.motor.zonas = remotas
            remotas.guardar(self.config.archivo_zonas, self.config.box)
            log.info("Zonas actualizadas desde el servidor (%s) y guardadas en %s",
                     ", ".join(z.tipo for z in remotas), self.config.archivo_zonas.name)

    def detener(self) -> None:
        self._detener.set()

    # --- bucle principal --------------------------------------------------------------------

    def ejecutar(self) -> list[EventoDescarte]:
        log.info("Servicio de visión en marcha · box %s · detector %s · %s fps",
                 self.config.box, self.config.etiqueta_modelo, self.config.parametros.fps_muestreo)
        try:
            while not self._detener.is_set():
                fotograma = self.fuente.leer()
                if fotograma is None:
                    if self.publicador:
                        self.publicador.observacion.interrumpido()
                    if self.fuente.terminada:
                        break
                    continue
                if not self.procesar(fotograma):
                    break
        except KeyboardInterrupt:
            log.info("Detenido por el usuario")
        finally:
            if self._ultimo is not None:
                for c in self.motor.finalizar(self._ultimo.t, self._ultimo.momento):
                    self._emitir(c)
            if self.config.mostrar:
                cv2.destroyAllWindows()
        return self.eventos

    def procesar(self, f: Fotograma) -> bool:
        """Procesa un fotograma. Devuelve False si el usuario pidió salir desde la ventana."""
        self._ultimo = f
        if (self.zonas_dinamicas is None and not self.motor.zonas
                and not self._aviso_sin_zonas):
            log.warning("No hay zonas definidas: el sistema detecta pero no puede confirmar "
                        "descartes. Trázalas en PAN-09 o con  python -m vision --editar-zonas")
            self._aviso_sin_zonas = True

        detecciones = self.detector.detectar(f.imagen)
        tachos = [d for d in detecciones if d.clase in (RECIPIENTE_ROJO, RECIPIENTE_COMUN)]
        detecciones = [d for d in detecciones
                       if d.clase not in self.residuos or not es_el_tacho(d, tachos)]
        gasas = [d for d in detecciones if d.clase in self.residuos
                 and d.confianza >= self.config.umbrales_clase.get(d.clase, 0.0)]
        if self.zonas_dinamicas is not None:
            self.motor.zonas = self.zonas_dinamicas.actualizar(detecciones, f.t)
        else:
            self._verificar_alineacion(detecciones)
        self._vigilar_obstruccion(f, tachos)
        if self.publicador and not self.obstruida:
            self.publicador.observacion.observando(f.momento)
        self._guardar_recortes(f, gasas)

        if self.disparador is not None:
            self._mano = self.disparador.evaluar(detecciones, self.motor.zonas)
        for confirmado in self.motor.procesar(gasas, f.t, f.momento, self._mano.activa,
                                              self._mano.confianza):
            # Solo cuenta si los tachos se siguieron viendo después de que el objeto
            # desapareció: si se dejan de ver junto con él, algo tapó la vista.
            tapado = (self.zonas_dinamicas is not None and
                      self._ultimo_tacho_t is not None and
                      self._ultimo_tacho_t < confirmado.t + 0.3)
            if self.obstruida or tapado:
                self.no_registrados += 1
                log.warning("Descarte en %s NO registrado: vista obstruida (%s)",
                            confirmado.zona, self.motivo_obstruccion or "tachos tapados")
                continue
            self._emitir(confirmado)

        if self.config.mostrar:
            return self._mostrar(f, detecciones)
        return True

    def _guardar_recortes(self, f: Fotograma, gasas: list[Deteccion]) -> None:
        """Último recorte de cada zona en el que se vio una gasa: será la evidencia."""
        for det in gasas:
            if det.confianza < self.config.parametros.umbral_confianza:
                continue
            zona_tipo = self.motor.zona_de(det)
            if zona_tipo:
                recorte = recortar(f.imagen, self.motor.zonas.get(zona_tipo))
                if recorte is not None:
                    self._recortes[zona_tipo] = recorte

    @staticmethod
    def _imagen_tapada(imagen: np.ndarray) -> bool:
        """Lente tapado o cámara contra algo: casi negro o sin textura."""
        chica = cv2.cvtColor(cv2.resize(imagen, (64, 36), interpolation=cv2.INTER_AREA),
                             cv2.COLOR_BGR2GRAY)
        return float(chica.mean()) < 25 or float(chica.std()) < 12

    def _vigilar_obstruccion(self, f: Fotograma, tachos: list[Deteccion]) -> None:
        """Decide si la vista está obstruida. Mira lo que el modelo ve en este fotograma, no
        las zonas, que se retienen varios segundos cuando un tacho deja de verse."""
        if self._ultimo_tacho_t is None or any(
                d.confianza >= CONFIANZA_TACHO_VISTO for d in tachos):
            self._ultimo_tacho_t = f.t
        # Sin tildes: OpenCV no las dibuja en la vista previa.
        motivo = ""
        if self._imagen_tapada(f.imagen):
            motivo = "camara tapada"
        elif self.zonas_dinamicas is not None and f.t - self._ultimo_tacho_t >= OBSTRUCCION_S:
            motivo = "no se ven los tachos"
        elif self.obstruida:
            # Histéresis: para despejar, los tachos se tienen que ver seguidos 1 s (un
            # cuadro suelto con un tacho no basta; si no, el estado parpadea).
            if f.t - self._ultimo_tacho_t > 0.5:
                self._despejada_desde = None
            elif self._despejada_desde is None:
                self._despejada_desde = f.t
            if self._despejada_desde is None or f.t - self._despejada_desde < 1.0:
                motivo = self.motivo_obstruccion
        obstruida = bool(motivo)
        if obstruida and not self.obstruida:
            self._despejada_desde = None
            log.warning("Vista obstruida (%s): el proceso no se registra hasta despejarla.",
                        motivo)
            if self.publicador:
                self.publicador.observacion.interrumpido()
        elif self.obstruida and not obstruida:
            log.info("Vista despejada: se vuelve a registrar (%s)", ", ".join(
                NOMBRE_ZONA[z.tipo] for z in self.motor.zonas) or "sin zonas")
        self.obstruida, self.motivo_obstruccion = obstruida, motivo
        if self.zonas_dinamicas is not None:
            self._zonas_alineadas = not obstruida

    def _verificar_alineacion(self, detecciones: list[Deteccion]) -> None:
        """Si el detector ve los recipientes fuera de sus zonas, la cámara se movió."""
        resultados = []
        for clase, tipo in ((RECIPIENTE_ROJO, ROJO), (RECIPIENTE_COMUN, COMUN)):
            zona = self.motor.zonas.get(tipo)
            dets = [d for d in detecciones if d.clase == clase]
            if zona is None or not dets:
                continue
            mejor = max(dets, key=lambda d: d.confianza)
            cx, cy = mejor.centro
            x0, y0, x1, y1 = zona.caja_px(self.config.ancho, self.config.alto, margen=0.6)
            resultados.append(x0 <= cx <= x1 and y0 <= cy <= y1)
        if resultados:
            alineadas = all(resultados)
            if self._zonas_alineadas and not alineadas:
                log.warning("Los recipientes no coinciden con sus zonas: ¿se movió la cámara? "
                            "Revisa PAN-09 antes de seguir.")
            self._zonas_alineadas = alineadas

    def _emitir(self, c: Confirmado) -> None:
        evidencia = None
        if c.zona == COMUN or self.config.evidencia_conformes:
            recorte = self._recortes.get(c.zona)
            if recorte is not None:
                evidencia = a_jpeg(recorte)
        evento = EventoDescarte(
            id_externo=id_externo_para(self.config.box, c.ocurrido_en),
            box=self.config.box,
            recipiente=c.zona,
            confianza=c.confianza,
            ocurrido_en=c.ocurrido_en,
            modelo=self.config.etiqueta_modelo,
            rasgos=c.rasgos,
            evidencia_jpeg=evidencia,
        )
        self.eventos.append(evento)
        if self.cola is not None:
            self.cola.encolar(evento.como_payload())
        log.info("► %s · %s · confianza %.2f · %s", evento.id_externo,
                 "CONFORME (rojo)" if c.zona == ROJO else "NO CONFORME (común)",
                 c.confianza, c.ocurrido_en.strftime("%H:%M:%S"))
        if self.al_confirmar:
            self.al_confirmar(evento)

    # --- vista previa -------------------------------------------------------------------------

    def _mostrar(self, f: Fotograma, detecciones: list[Deteccion]) -> bool:
        lienzo = f.imagen.copy()
        # Texto y líneas proporcionales al tamaño de trabajo (640 × 480 o 1920 × 1080).
        k = max(1.0, f.ancho / 640)
        grosor, fuente = max(2, round(2 * k)), 0.5 * k
        for zona in self.motor.zonas:
            pts = np.array(zona.puntos_px(f.ancho, f.alto), dtype=np.int32)
            cv2.polylines(lienzo, [pts], True, COLOR_ZONA[zona.tipo], grosor)
            x, y = pts.min(axis=0)
            cv2.putText(lienzo, NOMBRE_ZONA[zona.tipo], (int(x), max(int(14 * k), int(y) - int(6 * k))),
                        cv2.FONT_HERSHEY_SIMPLEX, fuente, COLOR_ZONA[zona.tipo], grosor // 2, cv2.LINE_AA)
        # Solo lo que cuenta: el detector entrega cajas desde confianza muy baja para que las
        # reglas puedan cambiar el umbral en caliente, pero dibujarlas todas confunde.
        umbral_gasa = self.config.parametros.umbral_confianza
        visibles = quitar_contenidas([
            d for d in detecciones
            if d.confianza >= (umbral_gasa if d.clase in self.residuos else UMBRAL_DIBUJO)])
        for d in visibles:
            color = ((80, 200, 80) if d.clase == GASA else
                     (200, 80, 255) if d.clase in self.residuos else
                     (0, 165, 255) if d.clase == MANO else
                     (255, 170, 0) if d.clase == PERSONA else (180, 180, 0))
            cv2.rectangle(lienzo, (int(d.x0), int(d.y0)), (int(d.x1), int(d.y1)), color, grosor)
            cv2.putText(lienzo, f"{d.clase} {d.confianza:.2f}", (int(d.x0), int(d.y0) - int(4 * k)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9 * fuente, color, grosor // 2, cv2.LINE_AA)
        fps = self.fuente.fps_medido
        pie = f"{self.config.box} | {fps:.1f} fps | eventos: {len(self.eventos)}" if fps else \
            f"{self.config.box} | eventos: {len(self.eventos)}"
        if self.disparador is not None:
            pie += " | mano: " + ("SI" if self._mano.activa else "no")
        if self.publicador:
            pie += " | servidor: " + ("conectado" if self.publicador.conectado else "SIN CONEXION")
        if self.obstruida:
            alto_franja = int(44 * k)
            cv2.rectangle(lienzo, (0, 0), (f.ancho, alto_franja), (0, 0, 200), -1)
            cv2.putText(lienzo, f"PROCESO NO REGISTRADO: {self.motivo_obstruccion}",
                        (int(10 * k), int(30 * k)), cv2.FONT_HERSHEY_SIMPLEX, 1.1 * fuente,
                        (255, 255, 255), grosor, cv2.LINE_AA)
        if self.no_registrados:
            pie += f" | no registrados: {self.no_registrados}"
        cv2.putText(lienzo, pie + " | q para salir", (int(8 * k), f.alto - int(10 * k)),
                    cv2.FONT_HERSHEY_SIMPLEX, fuente, (255, 255, 255), grosor // 2, cv2.LINE_AA)
        if not self._ventana_lista:
            # Ventana redimensionable: a 1920 × 1080 no cabe entera con la barra de tareas.
            cv2.namedWindow(VENTANA_PREVIA, cv2.WINDOW_NORMAL)
            if f.ancho > 1280:
                cv2.resizeWindow(VENTANA_PREVIA, 1280, round(1280 * f.alto / f.ancho))
            self._ventana_lista = True
        cv2.imshow(VENTANA_PREVIA, lienzo)
        return (cv2.waitKey(1) & 0xFF) != ord("q")

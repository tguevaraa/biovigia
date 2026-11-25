"""M3 · Reglas espacio-temporales y confirmación del descarte (RF-03, RNF-07, RNF-16).

Separación entre percepción y decisión (Grekov et al., 2026): YOLO solo dice dónde hay
una gasa en cada fotograma; quien decide si hubo un descarte, y en qué recipiente, es esta
capa de reglas explícitas, auditable y ajustable sin reentrenar.

Un descarte se confirma cuando la trayectoria de una gasa:

1. termina dentro del polígono de un recipiente (su última observación está en la zona),
2. cumple la regla k-de-N: de sus últimas N observaciones, al menos k están en esa zona,
3. y la ausencia se sostiene durante la ventana de confirmación (la gasa no reaparece).

Además, se ignora la gasa que **ya estaba en el tacho**: la que casi no se movió en toda
su trayectoria (menos de ``desplazamiento_min``). Es una gasa de un descarte anterior que
reaparece o se pierde cuando una mano la tapa; contarla duplicaría el evento. Una gasa
que alguien trae y suelta recorre la imagen (en los clips propios, 150 a 190 px contra
0 a 15 px de las que ya estaban). No se usa «nunca estuvo fuera de la zona»: con la
cámara cenital la zona puede abarcar por donde entra la mano, y al arrancar los tachos
tardan unos fotogramas en confirmarse.

Una gasa que pasa cerca de la boca y se retira falla 1 o 2; una que reaparece antes de
la ventana cancela la confirmación. Cada pista produce como máximo un evento, y una
memoria de lo ya contado evita duplicar una gasa que queda a la vista dentro del recipiente.

Con el disparador por mano activo (``exige_mano``) hay una cuarta condición: la gasa tuvo
que aparecer junto a una mano. Una trayectoria que nace sin mano cerca —un reflejo, un
papel que ya estaba en el recipiente— no genera evento y queda en la memoria para que
tampoco lo genere si reaparece cuando una mano le pasa por encima.
"""
from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .configuracion import ParametrosReglas
from .seguimiento import Seguidor
from .tipos import Deteccion
from .zonas import ConjuntoZonas

log = logging.getLogger("vision.reglas")


@dataclass
class Observacion:
    t: float
    momento: datetime
    zona: Optional[str]
    confianza: float
    area: float
    centro: tuple[float, float]
    clase: str = "gasa"


@dataclass
class Historial:
    """Trayectoria de una gasa seguida."""

    pista_id: int
    observaciones: deque = field(default_factory=lambda: deque(maxlen=120))
    cerrada: bool = False
    residual: bool = False  # nació sobre una gasa ya contada: no genera eventos
    vio_mano: bool = True   # con el disparador activo: apareció junto a una mano
    confianza_mano: float = 0.0
    # Mayor distancia al punto donde nació, en píxeles. Se lleva aparte porque la cola
    # ``observaciones`` olvida lo más viejo.
    desplazamiento_max: float = 0.0

    @property
    def ultima(self) -> Observacion:
        return self.observaciones[-1]

    @property
    def primera(self) -> Observacion:
        return self.observaciones[0]

    def ultimas(self, n: int) -> list[Observacion]:
        return list(self.observaciones)[-n:]

    def racha_en_zona(self) -> list[Observacion]:
        """Observaciones consecutivas, desde la última hacia atrás, en la misma zona."""
        if not self.observaciones or self.ultima.zona is None:
            return []
        zona = self.ultima.zona
        racha = []
        for obs in reversed(self.observaciones):
            if obs.zona != zona:
                break
            racha.append(obs)
        return list(reversed(racha))


@dataclass
class Decision:
    zona: str
    confianza: float
    rasgos: dict


# --- Estrategias de confirmación (Strategy) -----------------------------------------------------

class ReglaConfirmacion(ABC):
    nombre = "abstracta"

    @abstractmethod
    def decidir(self, h: Historial, p: ParametrosReglas, motivo: str) -> Optional[Decision]: ...


def rasgos_de(h: Historial, zona: str, p: ParametrosReglas, motivo: str) -> dict:
    """Rasgos que se guardan con cada evento para entrenar después el clasificador."""
    ventana = h.ultimas(p.n_confirmacion)
    en_zona = [o for o in ventana if o.zona == zona]
    todas_en_zona = [o for o in h.observaciones if o.zona == zona]
    return {
        "fotogramas_confirmacion": len(en_zona),
        "observaciones": len(h.observaciones),
        "fraccion_en_zona": round(len(todas_en_zona) / len(h.observaciones), 3),
        "duracion_s": round(h.ultima.t - h.primera.t, 2),
        "confianza_media": round(sum(o.confianza for o in en_zona) / max(1, len(en_zona)), 3),
        "area_media_px": round(sum(o.area for o in en_zona) / max(1, len(en_zona))),
        "k": p.k_confirmacion,
        "n": p.n_confirmacion,
        "motivo": motivo,
    }


class ReglaKdeN(ReglaConfirmacion):
    nombre = "k-de-N"

    def decidir(self, h: Historial, p: ParametrosReglas, motivo: str) -> Optional[Decision]:
        if not h.observaciones:
            return None
        if h.ultima.zona is None:
            return None  # la trayectoria no terminó dentro de un recipiente
        ventana = h.ultimas(p.n_confirmacion)
        conteo = Counter(o.zona for o in ventana if o.zona is not None)
        # El recipiente es el más visto en la ventana, no el del último cuadro: con K=1 un
        # salto suelto de la caja hacia el tacho vecino cambiaba el recipiente del evento.
        # Empate: gana el más reciente.
        orden = [o.zona for o in reversed(ventana) if o.zona is not None]
        zona = max(conteo, key=lambda z: (conteo[z], -orden.index(z)))
        if conteo[zona] < min(p.k_confirmacion, p.n_confirmacion):
            return None  # pasó cerca, pero no lo bastante dentro
        rasgos = rasgos_de(h, zona, p, motivo)
        rasgos["regla"] = self.nombre
        return Decision(zona, rasgos["confianza_media"], rasgos)


class ReglaConClasificador(ReglaKdeN):
    """k-de-N y, además, un clasificador de scikit-learn entrenado con los ``rasgos``.

    El clasificador se carga con joblib y debe exponer ``predict_proba`` sobre el vector
    ``COLUMNAS``. Si falta o falla, la regla se comporta como k-de-N (degradación segura).
    """

    nombre = "k-de-N+clasificador"
    COLUMNAS = ("fotogramas_confirmacion", "observaciones", "fraccion_en_zona", "duracion_s",
                "confianza_media", "area_media_px")

    def __init__(self, ruta: Path, umbral: float = 0.5) -> None:
        self.umbral = umbral
        self.modelo = None
        try:
            import joblib

            self.modelo = joblib.load(ruta)
            log.info("Clasificador de confirmación cargado desde %s", ruta)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo degrada a k-de-N
            log.warning("No se pudo cargar el clasificador %s (%s); se usa solo k-de-N.",
                        ruta, exc)

    def decidir(self, h: Historial, p: ParametrosReglas, motivo: str) -> Optional[Decision]:
        decision = super().decidir(h, p, motivo)
        if decision is None or self.modelo is None:
            return decision
        vector = [[float(decision.rasgos[c]) for c in self.COLUMNAS]]
        probabilidad = float(self.modelo.predict_proba(vector)[0][1])
        decision.rasgos.update(regla=self.nombre, prob_clasificador=round(probabilidad, 3))
        return decision if probabilidad >= self.umbral else None


# --- Motor -----------------------------------------------------------------------------------

@dataclass
class Confirmado:
    """Resultado del motor: un descarte confirmado, todavía sin evidencia ni identificador."""

    zona: str
    confianza: float
    ocurrido_en: datetime
    t: float
    rasgos: dict
    pista_id: int


@dataclass
class _Recuerdo:
    zona: str
    centro: tuple[float, float]
    refrescado_t: float


class MotorConfirmacion:
    def __init__(self, zonas: ConjuntoZonas, parametros: ParametrosReglas,
                 regla: Optional[ReglaConfirmacion] = None, ancho: int = 640,
                 alto: int = 480) -> None:
        self.zonas = zonas
        self.p = parametros
        self.regla = regla or ReglaKdeN()
        self.ancho, self.alto = ancho, alto
        self.seguidor = Seguidor(max_distancia_px=0.10 * ancho,
                                 max_perdida_s=parametros.ventana_confirmacion_s)
        self.historiales: dict[int, Historial] = {}
        self.memoria: list[_Recuerdo] = []
        self.descartadas = 0  # trayectorias que no se confirmaron (paso cercano, salida)
        self.ya_dentro = 0    # gasas que ya estaban en el recipiente (no se movieron)
        # Disparador por mano. Lo activa el servicio cuando el detector distingue manos.
        self.exige_mano = False
        self.sin_mano = 0     # trayectorias ignoradas por no haber aparecido con una mano
        self._ultima_mano_t: Optional[float] = None
        self._confianza_mano = 0.0

    def zona_de(self, det: Deteccion) -> Optional[str]:
        cx, cy = det.centro
        return self.zonas.zona_de(cx / self.ancho, cy / self.alto)

    def _cerca_de_recuerdo(self, zona: Optional[str], centro: tuple[float, float],
                           t: float) -> bool:
        radio = self.p.radio_memoria * self.ancho
        for r in self.memoria:
            if math.hypot(r.centro[0] - centro[0], r.centro[1] - centro[1]) <= radio:
                r.refrescado_t = t
                if zona is not None and zona == r.zona:
                    return True
        return False

    def _mano_reciente(self, t: float) -> bool:
        return (self._ultima_mano_t is not None
                and t - self._ultima_mano_t <= self.p.gracia_mano_s)

    def _actualizar_mano(self, h: Historial, zona: Optional[str], t: float) -> None:
        """Decide si la trayectoria apareció con una mano; si no, la deja como residual."""
        if not self.exige_mano or h.residual:
            return
        if self._mano_reciente(t):
            if not h.vio_mano and t - h.primera.t <= self.p.gracia_mano_s:
                h.vio_mano = True
            if h.vio_mano:
                h.confianza_mano = max(h.confianza_mano, self._confianza_mano)
        if not h.vio_mano and t - h.primera.t > self.p.gracia_mano_s:
            h.residual = True
            self.sin_mano += 1
            if zona is not None:
                self.memoria.append(_Recuerdo(zona, h.ultima.centro, t))

    def procesar(self, gasas: list[Deteccion], t: float, momento: datetime,
                 mano_activa: bool = False, confianza_mano: float = 0.0) -> list[Confirmado]:
        self.seguidor.max_perdida_s = self.p.ventana_confirmacion_s
        visibles = [d for d in gasas if d.confianza >= self.p.umbral_confianza]
        confirmados: list[Confirmado] = []
        if mano_activa:
            self._ultima_mano_t = t
            self._confianza_mano = confianza_mano

        for pista, es_nueva in self.seguidor.actualizar(visibles, t):
            det = pista.deteccion
            zona = self.zona_de(det)
            cerca = self._cerca_de_recuerdo(zona, det.centro, t)
            h = self.historiales.get(pista.id)
            if h is None:
                h = Historial(pista.id, residual=es_nueva and cerca,
                              vio_mano=not self.exige_mano or self._mano_reciente(t))
                self.historiales[pista.id] = h
            h.observaciones.append(Observacion(t, momento, zona, det.confianza, det.area,
                                               det.centro, det.clase))
            h.desplazamiento_max = max(h.desplazamiento_max, math.hypot(
                det.centro[0] - h.primera.centro[0], det.centro[1] - h.primera.centro[1]))
            self._actualizar_mano(h, zona, t)
            if not h.cerrada and not h.residual and h.vio_mano:
                c = self._por_permanencia(h, t)
                if c:
                    confirmados.append(c)

        # Trayectorias cuya ausencia ya se sostuvo la ventana completa.
        for pid, h in list(self.historiales.items()):
            if t - h.ultima.t < self.p.ventana_confirmacion_s:
                continue
            if not h.cerrada and not h.residual:
                c = self._confirmar(h, "desaparicion") if h.vio_mano else None
                if c:
                    confirmados.append(c)
                elif h.vio_mano:
                    self.descartadas += 1
                    if len(h.observaciones) >= 3:
                        log.info("Pista %s (%s) sin descarte: %d obs., %d en zona, termina en %s (%.0f, %.0f)",
                                 h.pista_id, h.ultima.clase, len(h.observaciones),
                                 sum(o.zona is not None for o in h.observaciones), h.ultima.zona or "fuera",
                                 *h.ultima.centro)
                else:
                    self.sin_mano += 1
            del self.historiales[pid]
            self.seguidor.olvidar(pid)

        self.memoria = [r for r in self.memoria if t - r.refrescado_t <= self.p.memoria_s]
        return confirmados

    def _por_permanencia(self, h: Historial, t: float) -> Optional[Confirmado]:
        """La gasa quedó visible y quieta dentro del recipiente (recipiente sin tapa)."""
        if self.p.permanencia_s <= 0:
            return None  # desactivado
        racha = h.racha_en_zona()
        if len(racha) < self.p.k_confirmacion:
            return None
        if racha[-1].t - racha[0].t < self.p.permanencia_s:
            return None
        xs = [o.centro[0] for o in racha]
        ys = [o.centro[1] for o in racha]
        if max(max(xs) - min(xs), max(ys) - min(ys)) > 0.025 * self.ancho:
            return None  # todavía se está moviendo
        return self._confirmar(h, "permanencia")

    def _por_caida(self, h: Historial) -> Optional[Decision]:
        """El objeto venía bajando y desapareció justo encima de un recipiente."""
        if self.p.alcance_caida <= 0 or h.ultima.zona is not None or len(h.observaciones) < 3:
            return None
        clases = [o.clase for o in h.observaciones]
        if max(set(clases), key=clases.count) not in self.p.clases_caida:
            return None
        ultima = h.ultima
        recientes = [o for o in h.observaciones if ultima.t - o.t <= 0.4]
        if ultima.centro[1] - recientes[0].centro[1] < 0.015 * self.alto:
            return None  # no estaba cayendo (sostenido en el aire o subiendo)
        x, y = ultima.centro[0] / self.ancho, ultima.centro[1] / self.alto
        mejor = None
        for z in self.zonas:
            xs = [px for px, _ in z.puntos]
            ys = [py for _, py in z.puntos]
            arriba = min(ys)
            alcance = self.p.alcance_caida * (max(ys) - arriba)
            if min(xs) <= x <= max(xs) and arriba - alcance <= y < arriba:
                if mejor is None or arriba - y < mejor[0]:
                    mejor = (arriba - y, z.tipo)
        if mejor is None:
            return None
        zona = mejor[1]
        rasgos = rasgos_de(h, zona, self.p, "caida")
        ventana = h.ultimas(self.p.n_confirmacion)
        rasgos["confianza_media"] = round(sum(o.confianza for o in ventana) / len(ventana), 3)
        rasgos["regla"] = "caida-proyectada"
        return Decision(zona, rasgos["confianza_media"], rasgos)

    def _confirmar(self, h: Historial, motivo: str) -> Optional[Confirmado]:
        decision = self.regla.decidir(h, self.p, motivo)
        if decision is None and motivo == "desaparicion":
            decision = self._por_caida(h)
        if decision is None:
            return None
        if h.desplazamiento_max < self.p.desplazamiento_min * self.ancho:
            # No se movió: ya estaba dentro del recipiente. Se recuerda para que tampoco
            # cuente si vuelve a aparecer.
            h.cerrada = h.residual = True
            self.ya_dentro += 1
            self.memoria.append(_Recuerdo(decision.zona, h.ultima.centro, h.ultima.t))
            log.debug("Pista %s ignorada: ya estaba en %s", h.pista_id, decision.zona)
            return None
        h.cerrada = True
        # Qué residuo era: la clase más vista en la trayectoria (gasa, tubo, jeringa…).
        clases = [o.clase for o in h.observaciones]
        decision.rasgos["objeto"] = max(set(clases), key=clases.count)
        if self.exige_mano:
            decision.rasgos.update(mano_detectada=True,
                                   confianza_mano=round(h.confianza_mano, 3))
        ultima = h.ultima
        self.memoria.append(_Recuerdo(decision.zona, ultima.centro, ultima.t))
        log.info("Descarte confirmado en %s (pista %s, %s, %s obs. en zona)", decision.zona,
                 h.pista_id, motivo, decision.rasgos["fotogramas_confirmacion"])
        return Confirmado(decision.zona, decision.confianza, ultima.momento, ultima.t,
                          decision.rasgos, h.pista_id)

    def finalizar(self, t: float, momento: datetime) -> list[Confirmado]:
        """Cierra las trayectorias pendientes (fin de un video): adelanta el reloj."""
        avance = self.p.ventana_confirmacion_s + 0.001
        return self.procesar([], t + avance, momento + timedelta(seconds=avance))

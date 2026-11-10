"""Turnos y fechas en la zona horaria del proyecto (America/Guayaquil)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

FUERA_DE_TURNO = "fuera_de_turno"


@dataclass(frozen=True)
class Turno:
    codigo: str
    etiqueta: str
    hora_inicio: int
    hora_fin: int  # excluida

    @property
    def horas(self) -> range:
        return range(self.hora_inicio, self.hora_fin)

    def rango(self, fecha: date) -> tuple[datetime, datetime]:
        tz = timezone.get_current_timezone()
        inicio = datetime.combine(fecha, time(self.hora_inicio), tzinfo=tz)
        fin = datetime.combine(fecha, time(0), tzinfo=tz) + timedelta(hours=self.hora_fin)
        return inicio, fin


def turnos() -> list[Turno]:
    return [Turno(*t) for t in settings.BIOVIGIA_TURNOS]


def turno_por_codigo(codigo: str) -> Turno | None:
    return next((t for t in turnos() if t.codigo == codigo), None)


def ahora() -> datetime:
    return timezone.localtime()


def hoy() -> date:
    return ahora().date()


def turno_de(momento: datetime) -> str:
    """Código del turno al que pertenece un instante, o ``fuera_de_turno``."""
    hora = timezone.localtime(momento).hour
    for t in turnos():
        if t.hora_inicio <= hora < t.hora_fin:
            return t.codigo
    return FUERA_DE_TURNO


def turno_actual() -> Turno:
    """Turno en curso; fuera de horario, el más cercano (para dar algo útil al tablero)."""
    hora = ahora().hour
    lista = turnos()
    for t in lista:
        if t.hora_inicio <= hora < t.hora_fin:
            return t
    if hora < lista[0].hora_inicio:
        return lista[0]
    return lista[-1]


def etiqueta_turno(codigo: str) -> str:
    t = turno_por_codigo(codigo)
    return t.etiqueta if t else "Fuera de turno"


def inicio_del_dia(fecha: date) -> datetime:
    return datetime.combine(fecha, time(0), tzinfo=timezone.get_current_timezone())


def rango_de_fechas(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """Intervalo [desde 00:00, hasta+1 00:00) en hora local."""
    return inicio_del_dia(desde), inicio_del_dia(hasta) + timedelta(days=1)

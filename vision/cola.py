"""Cola local en SQLite: ningún evento se pierde si el servidor no responde (RNF-12).

Los eventos se escriben aquí **antes** de intentar enviarlos y solo se borran cuando el
servidor responde 201 o 200 (duplicado). También guarda los tramos observados que no se
pudieron informar, para que el periodo no observado sea exacto tras una caída del servidor.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id_externo TEXT PRIMARY KEY,
    cuerpo TEXT NOT NULL,
    creado_en REAL NOT NULL,
    intentos INTEGER NOT NULL DEFAULT 0,
    proximo_intento REAL NOT NULL DEFAULT 0,
    ultimo_error TEXT
);
CREATE TABLE IF NOT EXISTS rechazados (
    id_externo TEXT PRIMARY KEY,
    cuerpo TEXT NOT NULL,
    motivo TEXT,
    rechazado_en REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tramos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio TEXT NOT NULL,
    fin TEXT NOT NULL
);
"""
ESPERA_MAXIMA_S = 60.0


class ColaLocal:
    def __init__(self, ruta: Path) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()
        with self._conexion() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        with self._candado:
            conexion = sqlite3.connect(self.ruta, timeout=10)
            try:
                conexion.execute("PRAGMA journal_mode=WAL")
                yield conexion
                conexion.commit()
            finally:
                conexion.close()

    # --- eventos ---------------------------------------------------------------------------

    def encolar(self, payload: dict) -> None:
        with self._conexion() as c:
            c.execute("INSERT OR IGNORE INTO eventos (id_externo, cuerpo, creado_en) "
                      "VALUES (?, ?, ?)",
                      (payload["id_externo"], json.dumps(payload), time.time()))

    def listos(self, limite: int = 20) -> list[tuple[str, dict, int]]:
        with self._conexion() as c:
            filas = c.execute(
                "SELECT id_externo, cuerpo, intentos FROM eventos WHERE proximo_intento <= ? "
                "ORDER BY creado_en LIMIT ?", (time.time(), limite)).fetchall()
        return [(i, json.loads(cuerpo), n) for i, cuerpo, n in filas]

    def confirmar(self, id_externo: str) -> None:
        with self._conexion() as c:
            c.execute("DELETE FROM eventos WHERE id_externo = ?", (id_externo,))

    def reintentar_despues(self, id_externo: str, error: str) -> float:
        """Espera exponencial: 2, 4, 8… hasta 60 s. Devuelve la espera aplicada."""
        with self._conexion() as c:
            fila = c.execute("SELECT intentos FROM eventos WHERE id_externo = ?",
                             (id_externo,)).fetchone()
            intentos = (fila[0] if fila else 0) + 1
            espera = min(ESPERA_MAXIMA_S, 2.0 ** intentos)
            c.execute("UPDATE eventos SET intentos = ?, proximo_intento = ?, ultimo_error = ? "
                      "WHERE id_externo = ?", (intentos, time.time() + espera, error[:300],
                                               id_externo))
        return espera

    def rechazar(self, id_externo: str, motivo: str) -> None:
        """El servidor dijo 422: no tiene sentido reintentar, pero no se borra sin rastro."""
        with self._conexion() as c:
            fila = c.execute("SELECT cuerpo FROM eventos WHERE id_externo = ?",
                             (id_externo,)).fetchone()
            if fila:
                c.execute("INSERT OR REPLACE INTO rechazados VALUES (?, ?, ?, ?)",
                          (id_externo, fila[0], motivo[:500], time.time()))
            c.execute("DELETE FROM eventos WHERE id_externo = ?", (id_externo,))

    def pendientes(self) -> int:
        with self._conexion() as c:
            return int(c.execute("SELECT COUNT(*) FROM eventos").fetchone()[0])

    def rechazados(self) -> int:
        with self._conexion() as c:
            return int(c.execute("SELECT COUNT(*) FROM rechazados").fetchone()[0])

    # --- tramos observados -----------------------------------------------------------------

    def guardar_tramo(self, inicio: datetime, fin: datetime) -> None:
        with self._conexion() as c:
            c.execute("INSERT INTO tramos (inicio, fin) VALUES (?, ?)",
                      (inicio.isoformat(), fin.isoformat()))

    def tramos(self, limite: int = 50) -> list[tuple[int, dict]]:
        with self._conexion() as c:
            filas = c.execute("SELECT id, inicio, fin FROM tramos ORDER BY id LIMIT ?",
                              (limite,)).fetchall()
        return [(i, {"inicio": a, "fin": b}) for i, a, b in filas]

    def borrar_tramos(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._conexion() as c:
            c.executemany("DELETE FROM tramos WHERE id = ?", [(i,) for i in ids])

    def ultimo_error(self) -> Optional[str]:
        with self._conexion() as c:
            fila = c.execute("SELECT ultimo_error FROM eventos WHERE ultimo_error IS NOT NULL "
                             "ORDER BY creado_en DESC LIMIT 1").fetchone()
        return fila[0] if fila else None

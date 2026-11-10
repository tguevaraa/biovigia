#!/usr/bin/env python
"""Punto de entrada de las utilidades de administración de Django."""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "biovigia.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - mensaje para el desarrollador
        raise ImportError(
            "No se pudo importar Django. ¿Activaste el entorno virtual e instalaste "
            "requirements-servidor.txt?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

"""Elimina la evidencia vencida según el periodo de retención (RNF-17).

Programable, por ejemplo, en el Programador de tareas de Windows una vez al día:
    python manage.py depurar_evidencia
"""
from django.core.management.base import BaseCommand

from vigilancia.servicios.retencion import depurar_evidencia_vencida


class Command(BaseCommand):
    help = "Borra los recortes de evidencia cuyo periodo de retención venció."

    def handle(self, *args, **opciones):
        borrados = depurar_evidencia_vencida()
        self.stdout.write(self.style.SUCCESS(f"✓ {borrados} evidencia(s) eliminada(s)"))

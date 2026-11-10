"""Deja la base lista para usar: box, recipientes, parámetros y (opcional) cuentas de prueba.

    python manage.py sembrar                    # box-2 con sus dos recipientes
    python manage.py sembrar --cuentas-demo     # además, una cuenta por rol y el token
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from rest_framework.authtoken.models import Token

from cuentas.models import Rol, Usuario
from vigilancia.models import Parametros
from vigilancia.servicios.recipientes import crear_box

CUENTAS_DEMO = [
    ("admin.demo", "Luis", "Andrade", Rol.ADMIN),
    ("supervisor.demo", "Paola", "Rivas", Rol.SUPERVISOR),
    ("limpieza.demo", "Rosa", "Vera", Rol.OPERATIVO),
]
CLAVE_DEMO = "BioVigIA-2026"


class Command(BaseCommand):
    help = "Crea el box del MVP, sus recipientes y los parámetros por defecto."

    def add_arguments(self, parser):
        parser.add_argument("--box", default="box-2", help="Código del puesto (por defecto box-2)")
        parser.add_argument("--nombre", default="Box 2")
        parser.add_argument("--cuentas-demo", action="store_true",
                            help=f"Crea una cuenta por rol con la clave {CLAVE_DEMO}")

    @transaction.atomic
    def handle(self, *args, **opciones):
        box = crear_box(opciones["box"], opciones["nombre"])
        Parametros.actual()
        self.stdout.write(self.style.SUCCESS(f"✓ {box.codigo} con recipientes rojo y común"))

        servicio, _ = Usuario.objects.get_or_create(
            username=f"vision-{box.codigo}",
            defaults={"rol": Rol.SERVICIO, "first_name": "Servicio de visión"})
        if servicio.rol != Rol.SERVICIO:
            servicio.rol = Rol.SERVICIO
            servicio.save(update_fields=["rol"])
        servicio.set_unusable_password()
        servicio.save(update_fields=["password"])
        token, _ = Token.objects.get_or_create(user=servicio)
        self.stdout.write(self.style.SUCCESS(f"✓ Token del servicio de visión: {token.key}"))
        self.stdout.write("  Ponlo en vision/.env como BIOVIGIA_TOKEN=<token>")

        if opciones["cuentas_demo"]:
            for username, nombre, apellido, rol in CUENTAS_DEMO:
                usuario, creado = Usuario.objects.get_or_create(
                    username=username,
                    defaults={"first_name": nombre, "last_name": apellido, "rol": rol})
                if creado:
                    usuario.set_password(CLAVE_DEMO)
                    usuario.save()
                estado = "creada" if creado else "ya existía"
                self.stdout.write(f"  · {username} ({rol}) {estado}")
            self.stdout.write(self.style.WARNING(
                f"  Clave de las cuentas demo: {CLAVE_DEMO}. No las uses en producción."))

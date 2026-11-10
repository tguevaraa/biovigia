"""Muestra (o regenera) el token del servicio de visión de un box.

    python manage.py token_vision --box box-2
    python manage.py token_vision --box box-2 --regenerar
"""
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from cuentas.models import Rol, Usuario


class Command(BaseCommand):
    help = "Muestra o regenera el token del servicio de visión."

    def add_arguments(self, parser):
        parser.add_argument("--box", default="box-2")
        parser.add_argument("--regenerar", action="store_true")

    def handle(self, *args, **opciones):
        try:
            usuario = Usuario.objects.get(username=f"vision-{opciones['box']}", rol=Rol.SERVICIO)
        except Usuario.DoesNotExist as exc:
            raise CommandError("No existe la cuenta del servicio. Ejecuta antes: "
                               "python manage.py sembrar") from exc
        if opciones["regenerar"]:
            Token.objects.filter(user=usuario).delete()
        token, _ = Token.objects.get_or_create(user=usuario)
        self.stdout.write(token.key)

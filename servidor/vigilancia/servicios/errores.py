"""Errores de dominio. La capa de API los traduce al formato del contrato."""


class ErrorDominio(Exception):
    """Regla de negocio incumplida."""

    codigo = "regla_de_negocio"
    estado_http = 409

    def __init__(self, detalle: str, campo: str | None = None) -> None:
        super().__init__(detalle)
        self.detalle = detalle
        self.campo = campo


class ErrorValidacion(ErrorDominio):
    codigo = "validacion"
    estado_http = 422


class RecipienteNoContaminado(ErrorDominio):
    """HU-03, criterio 3: no se registra el recambio de un recipiente que está normal."""

    codigo = "no_contaminado"
    estado_http = 409

    def __init__(self) -> None:
        super().__init__(
            "El recipiente ya está en estado normal; no hace falta registrar el recambio."
        )


class NoEncontrado(ErrorDominio):
    codigo = "no_encontrado"
    estado_http = 404


class CamaraInsuficiente(ErrorDominio):
    """HU-01, criterio 3: no se guardan zonas si la cámara no entrega 15 fps."""

    codigo = "camara_insuficiente"
    estado_http = 409

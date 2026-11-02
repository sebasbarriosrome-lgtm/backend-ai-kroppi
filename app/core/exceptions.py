class ReglaNegocio(Exception):
    """Error esperado (404, 400...). El handler HTTP lo convierte en respuesta."""

    def __init__(self, status: int, mensaje: str):
        self.status, self.mensaje = status, mensaje

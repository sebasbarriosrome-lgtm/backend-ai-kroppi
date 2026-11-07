import threading

from supabase import Client, create_client

from app.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

_local = threading.local()


def _cliente_del_hilo() -> Client:
    cliente = getattr(_local, "cliente", None)
    if cliente is None:
        cliente = _local.cliente = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return cliente


class _ClientePorHilo:
    """Un cliente de Supabase por hilo.

    El cliente síncrono usa una conexión HTTP/2 que no es segura entre hilos: las
    consultas que corren en paralelo con `run_in_threadpool` (p. ej. el
    `asyncio.gather` de stats/timeline/informes, o dos peticiones simultáneas)
    cortaban la conexión con `RemoteProtocolError: Server disconnected`.
    """

    def __getattr__(self, nombre: str):
        return getattr(_cliente_del_hilo(), nombre)


supabase_client: Client = _ClientePorHilo()  # type: ignore[assignment]

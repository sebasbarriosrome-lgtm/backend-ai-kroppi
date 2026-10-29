"""Supabase Storage por API REST, con la clave de servidor (se salta las políticas del bucket)."""
import logging

import httpx

from app import config

log = logging.getLogger("kroppi.storage")

_BASE = f"{config.SUPABASE_URL}/storage/v1"
_AUTH = {
    "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
}


async def subir_imagen(http: httpx.AsyncClient, ruta: str, contenido: bytes) -> None:
    r = await http.post(
        f"{_BASE}/object/{config.SUPABASE_BUCKET}/{ruta}",
        content=contenido,
        headers={**_AUTH, "Content-Type": "image/jpeg", "x-upsert": "false"},
    )
    r.raise_for_status()


async def eliminar_imagen(http: httpx.AsyncClient, ruta: str) -> None:
    """Limpieza de mejor esfuerzo; nunca lanza excepción."""
    try:
        await http.request(
            "DELETE", f"{_BASE}/object/{config.SUPABASE_BUCKET}",
            json={"prefixes": [ruta]}, headers=_AUTH,
        )
    except Exception:
        log.warning("No se pudo eliminar %s del bucket", ruta)


async def firmar_urls(http: httpx.AsyncClient, rutas: list[str]) -> dict[str, str]:
    """Devuelve {ruta: URL temporal}. Si falla, devuelve {} y la API responde con la ruta."""
    if not rutas:
        return {}
    try:
        r = await http.post(
            f"{_BASE}/object/sign/{config.SUPABASE_BUCKET}",
            json={"expiresIn": config.SIGNED_URL_SEGUNDOS, "paths": rutas},
            headers=_AUTH,
        )
        r.raise_for_status()
        return {
            item["path"]: f"{_BASE}{item['signedURL']}"
            for item in r.json()
            if item.get("path") and item.get("signedURL")
        }
    except Exception:
        log.exception("No se pudieron firmar las URLs de las imágenes")
        return {}

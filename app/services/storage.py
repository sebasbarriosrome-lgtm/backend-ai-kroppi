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


async def subir_objeto(
    http: httpx.AsyncClient, bucket: str, ruta: str, contenido: bytes, content_type: str
) -> None:
    r = await http.post(
        f"{_BASE}/object/{bucket}/{ruta}",
        content=contenido,
        headers={**_AUTH, "Content-Type": content_type, "x-upsert": "true"},
    )
    r.raise_for_status()


async def eliminar_objeto(http: httpx.AsyncClient, bucket: str, ruta: str) -> None:
    r = await http.request(
        "DELETE",
        f"{_BASE}/object/{bucket}",
        json={"prefixes": [ruta]},
        headers=_AUTH,
    )
    r.raise_for_status()


async def firmar_objeto(http: httpx.AsyncClient, bucket: str, ruta: str) -> str:
    r = await http.post(
        f"{_BASE}/object/sign/{bucket}/{ruta}",
        json={"expiresIn": config.SIGNED_URL_SEGUNDOS},
        headers=_AUTH,
    )
    r.raise_for_status()
    signed_url = r.json().get("signedURL")
    if not signed_url:
        raise RuntimeError("Storage no devolvió una URL firmada.")
    return f"{_BASE}{signed_url}"


async def firmar_objetos(http: httpx.AsyncClient, bucket: str, rutas: list[str]) -> dict[str, str]:
    if not rutas:
        return {}
    response = await http.post(
        f"{_BASE}/object/sign/{bucket}",
        json={"expiresIn": config.SIGNED_URL_SEGUNDOS, "paths": rutas},
        headers=_AUTH,
    )
    response.raise_for_status()
    result = {
        item["path"]: f"{_BASE}{item['signedURL']}"
        for item in response.json()
        if item.get("path") and item.get("signedURL")
    }
    if any(path not in result for path in rutas):
        raise RuntimeError("Storage no devolvió todas las URLs firmadas solicitadas.")
    return result


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
            "DELETE",
            f"{_BASE}/object/{config.SUPABASE_BUCKET}",
            json={"prefixes": [ruta]},
            headers=_AUTH,
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

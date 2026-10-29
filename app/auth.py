"""Valida el token (JWT) que la app obtiene al iniciar sesión con Supabase Auth.
De ahí sale el id del usuario; NUNCA se confía en un user_id enviado por el cliente."""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app import config

_ISSUER = f"{config.SUPABASE_URL}/auth/v1"
# Claves públicas del proyecto (solo existen si usa firma asimétrica ES256/RS256)
_jwks = PyJWKClient(f"{_ISSUER}/.well-known/jwks.json", cache_keys=True, lifespan=3600)
_esquema = HTTPBearer(auto_error=False)


@dataclass
class Usuario:
    id: str
    email: str | None


def _verificar(token: str) -> dict:
    """Función síncrona (puede consultar la red la primera vez para traer las claves)."""
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg in ("ES256", "RS256"):
            clave = _jwks.get_signing_key_from_jwt(token).key
            return jwt.decode(token, clave, algorithms=[alg],
                              audience="authenticated", issuer=_ISSUER)
        if alg == "HS256" and config.SUPABASE_JWT_SECRET:
            return jwt.decode(token, config.SUPABASE_JWT_SECRET, algorithms=["HS256"],
                              audience="authenticated", issuer=_ISSUER)
    except jwt.PyJWTError:
        pass
    raise HTTPException(401, "Sesión inválida o expirada. Inicia sesión de nuevo.")


async def usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_esquema),
) -> Usuario:
    if credenciales is None:
        raise HTTPException(401, "Falta el token de sesión (Authorization: Bearer ...).")
    claims = await run_in_threadpool(_verificar, credenciales.credentials)
    if not claims.get("sub"):
        raise HTTPException(401, "Token sin identificador de usuario.")
    return Usuario(id=claims["sub"], email=claims.get("email"))

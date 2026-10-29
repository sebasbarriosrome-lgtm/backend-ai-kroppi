import asyncio
import json
import logging

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT

log = logging.getLogger("kroppi.gemini")

_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_cache: dict[str, list[str]] = {}   # por enfermedad; se reinicia al reiniciar el servidor

PROMPT = """Eres un asistente de apoyo para caficultores. Un modelo de visión por computador \
detectó posiblemente esta condición en una foto de una hoja de café:

- Nombre: {name}
- Agente: {scientific_name} ({pathogen_type})
- Síntomas típicos: {symptoms}

Escribe de 3 a 5 recomendaciones breves y prácticas para el productor.

Reglas:
- Español sencillo, sin tecnicismos innecesarios.
- Cada recomendación con máximo 25 palabras.
- Enfócate en monitoreo del lote, prácticas culturales, sanidad del cultivo y manejo integrado.
- NO menciones nombres comerciales, dosis ni concentraciones de agroquímicos.
- Una de las recomendaciones debe indicar confirmar el diagnóstico con un agrónomo o técnico de campo.
- Habla del diagnóstico como una posibilidad, no como una certeza.

Responde SOLO con un arreglo JSON de strings, sin texto adicional."""


async def obtener_recomendaciones(enfermedad: dict) -> list[str]:
    """Recomendaciones de Gemini. Si algo falla devuelve [] y el diagnóstico sigue funcionando."""
    if _client is None:
        log.warning("GEMINI_API_KEY no configurada; se omiten las recomendaciones.")
        return []
    codigo = enfermedad["code"]
    if codigo in _cache:
        return _cache[codigo]

    prompt = PROMPT.format(
        name=enfermedad["name"],
        scientific_name=enfermedad["scientific_name"] or "no especificado",
        pathogen_type=enfermedad["pathogen_type"] or "no especificado",
        symptoms="; ".join(enfermedad["symptoms"]) or "no especificados",
    )
    try:
        respuesta = await asyncio.wait_for(
            _client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.3
                ),
            ),
            timeout=GEMINI_TIMEOUT,
        )
        datos = json.loads(respuesta.text)
        recomendaciones = [str(r).strip() for r in datos if str(r).strip()][:5]
        if recomendaciones:
            _cache[codigo] = recomendaciones
        return recomendaciones
    except Exception:
        log.exception("Falló la llamada a Gemini")
        return []

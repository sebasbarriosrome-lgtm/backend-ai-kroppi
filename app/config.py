import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

# --- Variables obligatorias: si faltan, el servidor no arranca y dice cuáles ---
_REQUERIDAS = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL"]
_faltan = [n for n in _REQUERIDAS if not os.getenv(n)]
if _faltan:
    raise RuntimeError("Faltan variables en el archivo .env: " + ", ".join(_faltan))

# --- Supabase ---
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET") or None   # solo proyectos con HS256
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "diagnosticos")
SIGNED_URL_SEGUNDOS = 3600

# --- Base de datos (SQLAlchemy necesita el prefijo del driver) ---
DATABASE_URL = os.environ["DATABASE_URL"]
for _prefijo in ("postgresql://", "postgres://"):
    if DATABASE_URL.startswith(_prefijo):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len(_prefijo):]
        break

# --- Gemini (opcional: sin clave, las recomendaciones quedan vacías) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "15"))

# --- Modelo ---
MODEL_DIR = BASE_DIR / "model_files"
TFLITE_PATH = MODEL_DIR / "kroppi_cafe_v2.tflite"
CONFIG_PATH = MODEL_DIR / "kroppi_config.json"
MODEL_VERSION = "v2"
with open(CONFIG_PATH, encoding="utf-8") as f:
    MODEL_CONFIG = json.load(f)   # class_names, umbral, img_size

# --- Mapeo: clase que devuelve el modelo -> `code` de la tabla diseases ---
# (la tabla diseases no tiene columna model_class, así que el mapeo vive aquí)
# --- Mapeo: clase del modelo -> código de enfermedad ---
CLASE_A_CODIGO = {
    "Coffee___healthy": "cafe_sano",
    "Coffee___rust": "roya_cafe",
    "Coffee__phoma": "phoma_cafe",
    "Coffee_miner": "minador_cafe",
}
CODIGO_SANO = "cafe_sano"

_PENDIENTE = ["Consultar a un agrónomo para definir el manejo."]

# La tabla `diseases` ya no existe: el catálogo vive aquí (son solo 4 clases).
ENFERMEDADES = {
    "cafe_sano": {
        "code": "cafe_sano", "name": "Hoja sana", "scientific_name": None,
        "pathogen_type": None, "symptoms": [],
        "general_recommendations": ["No se detectó enfermedad en esta foto. Revisa visualmente si hay síntomas."],
        "requires_agronomist": False, "is_healthy": True,
    },
    "roya_cafe": {
        "code": "roya_cafe", "name": "Roya del café", "scientific_name": "Hemileia vastatrix",
        "pathogen_type": "Hongo",
        "symptoms": ["Manchas amarillo-anaranjadas en el envés de la hoja, con aspecto polvoso."],
        "general_recommendations": _PENDIENTE, "requires_agronomist": True, "is_healthy": False,
    },
    "phoma_cafe": {
        "code": "phoma_cafe", "name": "Phoma", "scientific_name": "Phoma spp.",
        "pathogen_type": "Hongo",
        "symptoms": ["Manchas oscuras necróticas en hojas jóvenes y brotes."],
        "general_recommendations": _PENDIENTE, "requires_agronomist": True, "is_healthy": False,
    },
    "minador_cafe": {
        "code": "minador_cafe", "name": "Minador de la hoja", "scientific_name": "Leucoptera coffeella",
        "pathogen_type": "Insecto (plaga)",
        "symptoms": ["Manchas irregulares y secas en la hoja, producidas por las larvas."],
        "general_recommendations": _PENDIENTE, "requires_agronomist": True, "is_healthy": False,
    },
}

# --- API ---
MAX_UPLOAD_MB = 10
CULTIVOS_SOPORTADOS = {"cafe"}   # cultivos para los que existe modelo
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

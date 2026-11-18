import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

_REQUERIDAS = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
_faltan = [n for n in _REQUERIDAS if not os.getenv(n)]
if _faltan:
    raise RuntimeError("Faltan variables en el archivo .env: " + ", ".join(_faltan))

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET") or None
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "diagnosticos")
SIGNED_URL_SEGUNDOS = 3600

WOMPI_PUBLIC_KEY = os.getenv("WOMPI_PUBLIC_KEY") or None
WOMPI_INTEGRITY_SECRET = os.getenv("WOMPI_INTEGRITY_SECRET") or None
WOMPI_CHECKOUT_URL = os.getenv("WOMPI_CHECKOUT_URL") or None
WOMPI_EVENTS_SECRET = os.getenv("WOMPI_EVENTS_SECRET") or None
WOMPI_PRIVATE_KEY = os.getenv("WOMPI_PRIVATE_KEY") or None
WOMPI_API_URL = os.getenv("WOMPI_API_URL", "https://sandbox.wompi.co/v1").rstrip("/")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "15"))

MODEL_DIR = BASE_DIR / "model_files"
TFLITE_PATH = MODEL_DIR / "kroppi_cafe_v2.tflite"
CONFIG_PATH = MODEL_DIR / "kroppi_config.json"
MODEL_VERSION = "v2"
with open(CONFIG_PATH, encoding="utf-8") as f:
    MODEL_CONFIG = json.load(f)
MAIZ_TFLITE_PATH = MODEL_DIR / "modelo_enfermedades_maiz.tflite"
MAIZ_CONFIG_PATH = MODEL_DIR / "maiz_config.json"
with open(MAIZ_CONFIG_PATH, encoding="utf-8") as f:
    MAIZ_MODEL_CONFIG = json.load(f)

CLASE_A_CODIGO = {
    "Coffee___healthy": "cafe_sano",
    "Coffee___rust": "roya_cafe",
    "Coffee__phoma": "phoma_cafe",
    "Coffee_miner": "minador_cafe",
}
CODIGO_SANO = "cafe_sano"

_PENDIENTE = ["Consultar a un agrónomo para definir el manejo."]

ENFERMEDADES = {
    "cafe_sano": {
        "code": "cafe_sano", "name": "Hoja sana", "scientific_name": None,
        "pathogen_type": None, "symptoms": [],
        "general_recommendations": [
            "No se detectó enfermedad en esta foto. Revisa visualmente si hay síntomas."
        ],
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
        "code": "minador_cafe", "name": "Minador de la hoja",
        "scientific_name": "Leucoptera coffeella",
        "pathogen_type": "Insecto (plaga)",
        "symptoms": ["Manchas irregulares y secas en la hoja, producidas por las larvas."],
        "general_recommendations": _PENDIENTE, "requires_agronomist": True, "is_healthy": False,
    },
    "maiz_sano": {
        "code": "maiz_sano", "name": "Maíz sano", "scientific_name": None,
        "pathogen_type": None, "symptoms": [],
        "general_recommendations": [
            "No se detectó enfermedad en esta foto. Revisa visualmente si hay síntomas."
        ],
        "requires_agronomist": False, "is_healthy": True,
    },
    "roya_maiz": {
        "code": "roya_maiz", "name": "Roya del maíz", "scientific_name": "Puccinia spp.",
        "pathogen_type": "Hongo",
        "symptoms": ["Pústulas pequeñas de color amarillo, anaranjado o café en las hojas."],
        "general_recommendations": _PENDIENTE, "requires_agronomist": True, "is_healthy": False,
    },
    "tizon_maiz": {
        "code": "tizon_maiz", "name": "Tizón foliar del maíz", "scientific_name": None,
        "pathogen_type": "Hongo",
        "symptoms": ["Lesiones alargadas y oscuras que pueden extenderse sobre las hojas."],
        "general_recommendations": _PENDIENTE, "requires_agronomist": True, "is_healthy": False,
    },
    "mancha_gris_maiz": {
        "code": "mancha_gris_maiz", "name": "Mancha gris del maíz",
        "scientific_name": "Cercospora spp.", "pathogen_type": "Hongo",
        "symptoms": ["Lesiones rectangulares de color grisáceo, delimitadas por las nervaduras."],
        "general_recommendations": _PENDIENTE, "requires_agronomist": True, "is_healthy": False,
    },
}

MAX_UPLOAD_MB = 10
CULTIVOS_SOPORTADOS = {"cafe", "maiz"}
CLASE_A_CODIGO_MAIZ = {
    "Maiz___healthy": "maiz_sano",
    "Maiz___roya": "roya_maiz",
    "Maiz___tizon": "tizon_maiz",
    "Maiz___mancha_gris": "mancha_gris_maiz",
}
MODEL_CONFIGS = {
    "cafe": {
        "tflite_path": TFLITE_PATH,
        "config": MODEL_CONFIG,
        "class_to_code": CLASE_A_CODIGO,
        "version": MODEL_VERSION,
    },
    "maiz": {
        "tflite_path": MAIZ_TFLITE_PATH,
        "config": MAIZ_MODEL_CONFIG,
        "class_to_code": CLASE_A_CODIGO_MAIZ,
        "version": "maiz-v1",
    },
}
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

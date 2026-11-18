import threading

import numpy as np
from PIL import Image

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    from tensorflow.lite.python.interpreter import Interpreter

from app.config import MODEL_CONFIGS


class Classifier:
    """Envuelve un modelo .tflite; la normalización ya está dentro del modelo."""

    def __init__(self, cultivo: str = "cafe"):
        try:
            modelo = MODEL_CONFIGS[cultivo]
        except KeyError as error:
            raise ValueError(f"No hay configuración de modelo para '{cultivo}'.") from error

        self.interpreter = Interpreter(model_path=str(modelo["tflite_path"]))
        self.interpreter.allocate_tensors()
        self._entrada = self.interpreter.get_input_details()[0]["index"]
        self._salida = self.interpreter.get_output_details()[0]["index"]
        self._lock = threading.Lock()
        self.class_names: list[str] = modelo["config"]["class_names"]
        self.umbral: float = modelo["config"]["umbral"]
        self.tamano = tuple(modelo["config"]["img_size"])
        self.class_to_code: dict[str, str] = modelo["class_to_code"]
        self.model_version: str = modelo["version"]

    def predict(self, imagen: Image.Image) -> np.ndarray:
        img = imagen.convert("RGB").resize(self.tamano, Image.BILINEAR)
        x = np.expand_dims(np.asarray(img, dtype=np.float32), 0)
        with self._lock:
            self.interpreter.set_tensor(self._entrada, x)
            self.interpreter.invoke()
            return self.interpreter.get_tensor(self._salida)[0].copy()

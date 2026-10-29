import threading

import numpy as np
from PIL import Image

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:  # alternativa si se instaló tensorflow
    from tensorflow.lite.python.interpreter import Interpreter

from app.config import MODEL_CONFIG, TFLITE_PATH


class Classifier:
    """Envuelve el modelo .tflite. La normalización ya está DENTRO del modelo:
    la imagen entra en valores 0-255, RGB, 224x224, sin dividir."""

    def __init__(self):
        self.interpreter = Interpreter(model_path=str(TFLITE_PATH))
        self.interpreter.allocate_tensors()
        self._entrada = self.interpreter.get_input_details()[0]["index"]
        self._salida = self.interpreter.get_output_details()[0]["index"]
        self._lock = threading.Lock()   # el intérprete no es seguro entre hilos
        self.class_names: list[str] = MODEL_CONFIG["class_names"]
        self.umbral: float = MODEL_CONFIG["umbral"]
        self.tamano = tuple(MODEL_CONFIG["img_size"])

    def predict(self, imagen: Image.Image) -> np.ndarray:
        img = imagen.convert("RGB").resize(self.tamano, Image.BILINEAR)
        x = np.expand_dims(np.asarray(img, dtype=np.float32), 0)
        with self._lock:
            self.interpreter.set_tensor(self._entrada, x)
            self.interpreter.invoke()
            return self.interpreter.get_tensor(self._salida)[0].copy()

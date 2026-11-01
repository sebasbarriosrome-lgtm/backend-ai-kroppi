"""Prueba el modelo con fotos sueltas, SIN la app ni la base de datos.

Uso (desde la carpeta del backend, con el .venv activo):

    python probar_modelo.py sana1.jpg roya1.jpg otra.png

Para cada foto muestra las 3 clases más probables con dos formas de escalar
la imagen. Sirve para saber si el modelo se equivoca con esas fotos o si la
API le está entregando la imagen en una escala distinta a la que espera.
"""
import sys

import numpy as np
from PIL import Image, ImageOps

from app.classifier import Classifier


def correr(clf: Classifier, imagen: Image.Image, escala: float) -> np.ndarray:
    img = imagen.convert("RGB").resize(clf.tamano, Image.BILINEAR)
    x = np.expand_dims(np.asarray(img, dtype=np.float32) * escala, 0)
    with clf._lock:
        clf.interpreter.set_tensor(clf._entrada, x)
        clf.interpreter.invoke()
        return clf.interpreter.get_tensor(clf._salida)[0].copy()


def main(rutas: list[str]) -> None:
    if not rutas:
        print("Uso: python probar_modelo.py foto1.jpg foto2.jpg ...")
        return

    clf = Classifier()
    print("Clases (en el orden del modelo):", clf.class_names)

    formas = (
        ("0-255 (como la API)", 1.0),
        ("0-1  (dividido /255)", 1.0 / 255.0),
    )
    for ruta in rutas:
        imagen = ImageOps.exif_transpose(Image.open(ruta))
        print(f"\n== {ruta}")
        for nombre, escala in formas:
            p = correr(clf, imagen, escala)
            orden = np.argsort(p)[::-1][:3]
            top = ", ".join(f"{clf.class_names[i]} {p[i]:.2f}" for i in orden)
            print(f"  {nombre:<22} -> {top}")


if __name__ == "__main__":
    main(sys.argv[1:])
# Firmas: convertir una firma escaneada o fotografiada en tinta negra con
# fondo transparente, lista para el carnet.
# Una firma NO se procesa con la IA de personas (por eso salia rota): es tinta
# oscura sobre papel claro, asi que se separa por luminosidad. Pasos: aplanar la
# iluminacion (sombras tipicas de foto de celular), umbral automatico, borde
# suave (antialias) y limpieza de motas de polvo/escaneo.
import cv2
import numpy as np
from PIL import Image
try:
    from PIL import ImageOps       # endereza fotos de celular (orientacion EXIF)
except Exception:                  # bundle viejo sin el modulo: sigue sin enderezar
    ImageOps = None


def procesar(ruta, carpeta_salida, nombre_salida=None, color="negro"):
    # Una firma FOTOGRAFIADA con celular puede venir "de costado" por la
    # orientacion EXIF (mismo bug que las selfies, feedback 2026-07-01): sin
    # esto el _firma.png final saldria girado 90 grados.
    img = Image.open(ruta)
    if ImageOps is not None:
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
    img = img.convert("RGB")
    gris = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)

    # Aplanar iluminacion: estimar el papel con un cierre morfologico grande y
    # dividir. Quita sombras y el tono del papel sin afectar la tinta.
    k = max(15, (min(gris.shape) // 20) | 1)  # impar, proporcional a la imagen
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    papel = cv2.morphologyEx(gris, cv2.MORPH_CLOSE, nucleo)
    plano = cv2.divide(gris, papel, scale=255)

    # Umbral automatico (Otsu) y alfa con transicion corta (borde antialias).
    # Ojo: para Otsu la tinta queda EN el valor t (inclusive), asi que la rampa
    # va de t (tinta solida) a t+suavidad (papel), no centrada en t.
    t, _ = cv2.threshold(plano, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    suavidad = max(8.0, (255.0 - t) * 0.25)
    alfa = np.clip((t + suavidad - plano.astype(np.float32)) / suavidad, 0.0, 1.0)

    # Quitar motas: manchitas diminutas que no son parte del trazo (se conserva
    # todo lo que tenga un tamano razonable, como puntos de la i o tildes).
    binaria = (alfa > 0.5).astype(np.uint8)
    n, etiquetas, stats, _ = cv2.connectedComponentsWithStats(binaria, connectivity=8)
    area_tinta = stats[1:, cv2.CC_STAT_AREA].sum() if n > 1 else 0
    if area_tinta:
        minimo = max(6, int(area_tinta * 0.0005))
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < minimo:
                alfa[etiquetas == i] = 0.0

    if not np.any(alfa > 0.5):
        raise ValueError("No se encontro un trazo de tinta. La firma debe ser "
                         "oscura sobre fondo claro (papel).")

    # Recortar al trazo + margen (la firma queda lista para ponerla en el carnet).
    ys, xs = np.where(alfa > 0.05)
    m = max(10, int(max(alfa.shape) * 0.03))
    y0, y1 = max(int(ys.min()) - m, 0), min(int(ys.max()) + m, alfa.shape[0] - 1)
    x0, x1 = max(int(xs.min()) - m, 0), min(int(xs.max()) + m, alfa.shape[1] - 1)
    alfa = alfa[y0:y1 + 1, x0:x1 + 1]

    # Tinta de un solo color (negra por defecto) sobre fondo transparente (PNG).
    # "blanco" sirve para diseños de carnet oscuros, donde la firma negra no se
    # veria. Solo cambia el color del trazo; la forma y el alfa son los mismos.
    a8 = (alfa * 255).astype(np.uint8)
    h, w = a8.shape
    lienzo = np.zeros((h, w, 4), dtype=np.uint8)
    if color == "blanco":
        lienzo[..., 0:3] = 255
    lienzo[..., 3] = a8
    final = Image.fromarray(lienzo, "RGBA")

    stem = nombre_salida if nombre_salida else ruta.stem
    destino = carpeta_salida / (stem + "_firma.png")
    final.save(destino, "PNG", dpi=(300, 300))
    return destino

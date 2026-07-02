# Encuadre: detectar la cara y calcular el recorte (que parte de la foto queda).
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import rutas


def ruta_cascade():
    # Ubica el archivo del detector de caras de OpenCV, tanto corriendo como
    # script (usa el de cv2) como empaquetado en .exe (lo busca en el bundle).
    nombre = "haarcascade_frontalface_default.xml"
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(Path(sys._MEIPASS) / "recursos" / nombre)
        candidatos.append(Path(sys._MEIPASS) / "cv2" / "data" / nombre)
    candidatos.append(rutas.BASE / "recursos" / nombre)
    try:
        candidatos.append(Path(cv2.data.haarcascades) / nombre)
    except Exception:
        pass
    for c in candidatos:
        if c.exists():
            return str(c)
    return str(Path(cv2.data.haarcascades) / nombre)


def detectar_cara(img_rgb):
    cascade = cv2.CascadeClassifier(ruta_cascade())
    gris = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2GRAY)
    caras = cascade.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    if len(caras) == 0:
        return None
    # La cara más grande es la del empleado (otras suelen ser ruido del fondo)
    return max(caras, key=lambda c: c[2] * c[3])


def recortar_region(img, left, top, ancho, alto, color_fondo):
    # Recorta una región que puede salirse de la imagen; lo que falte se
    # rellena con el color de fondo (evita bordes negros si la cara está al borde).
    lienzo = Image.new("RGB", (ancho, alto), tuple(color_fondo))
    src_x = max(0, left)
    src_y = max(0, top)
    src_x2 = min(img.width, left + ancho)
    src_y2 = min(img.height, top + alto)
    if src_x2 <= src_x or src_y2 <= src_y:
        return lienzo
    recorte = img.crop((src_x, src_y, src_x2, src_y2))
    lienzo.paste(recorte, (src_x - left, src_y - top))
    return lienzo


def recortar_alpha(alpha, left, top, ancho, alto):
    # Igual que recortar_region pero para la mascara (modo L); lo que sobra del
    # borde queda transparente (0). Sirve para el modo de fondo transparente.
    lienzo = Image.new("L", (ancho, alto), 0)
    sx = max(0, left)
    sy = max(0, top)
    sx2 = min(alpha.width, left + ancho)
    sy2 = min(alpha.height, top + alto)
    if sx2 <= sx or sy2 <= sy:
        return lienzo
    lienzo.paste(alpha.crop((sx, sy, sx2, sy2)), (sx - left, sy - top))
    return lienzo


def top_cabeza(alpha, ancho):
    # Fila más alta donde empieza la persona (tope del pelo), ignorando píxeles
    # sueltos: exige una cantidad mínima de píxeles en la fila para contar.
    arr = np.array(alpha) > 50
    min_px = max(5, int(ancho * 0.01))
    filas = arr.sum(axis=1)
    idx = np.where(filas >= min_px)[0]
    return int(idx[0]) if idx.size else None


def ancho_persona(alpha):
    # Columnas más a la izquierda y derecha donde hay persona (parte más ancha,
    # típicamente los hombros), ignorando píxeles sueltos: una columna cuenta
    # solo si tiene una cantidad mínima de píxeles verticales. Devuelve
    # (col_izq, col_der) o None si no hay silueta.
    arr = np.array(alpha) > 50
    alto = arr.shape[0]
    min_px = max(5, int(alto * 0.02))
    cols = arr.sum(axis=0)
    idx = np.where(cols >= min_px)[0]
    if idx.size == 0:
        return None
    return int(idx[0]), int(idx[-1])


def fila_hombros(alpha, col_izq, col_der):
    # Fila más BAJA donde la persona casi llena el ancho [col_izq, col_der]
    # (la línea de los hombros). Cortar el borde inferior del recorte aquí
    # evita esquinas blancas abajo: por debajo de los hombros el cuerpo se
    # angosta y aparecería blanco en las esquinas.
    arr = np.array(alpha) > 50
    objetivo = 0.95 * (col_der - col_izq)
    mejor = None
    for r in range(arr.shape[0]):
        cols = np.where(arr[r])[0]
        if cols.size and (cols[-1] - cols[0]) >= objetivo:
            mejor = r
    return mejor


def caja_encuadre(img_rgb, cara, alpha, preset):
    # Calcula la CAJA del recorte (left, top, ancho, alto). Devolver la caja (en
    # vez de la imagen ya recortada) permite aplicar el mismo recorte a la imagen
    # y a la mascara (para fondo transparente) y medir el color en el recorte.
    ancho_obj, alto_obj = preset["ancho_px"], preset["alto_px"]
    ratio = ancho_obj / alto_obj

    if cara is None:
        # Sin cara detectada: recorte centrado al aspecto destino.
        if img_rgb.width / img_rgb.height > ratio:
            crop_h = img_rgb.height
            crop_w = int(crop_h * ratio)
        else:
            crop_w = img_rgb.width
            crop_h = int(crop_w / ratio)
        left = (img_rgb.width - crop_w) // 2
        top = (img_rgb.height - crop_h) // 2
        return left, top, crop_w, crop_h

    x, y, w, h = cara
    cx = x + w / 2

    cabeza = top_cabeza(alpha, img_rgb.width)
    if cabeza is None:
        cabeza = y  # sin silueta: usar tope de la cara

    # Ancho tope por CABEZA: la cabeza (tope del pelo al mentón) debe ocupar
    # 'cabeza_relativa' del alto final. Sube/baja este valor para acercar
    # (rostro más grande) o alejar (se ve más cuerpo). Ajustable por trabajo.
    menton = y + h
    alto_cabeza = max(menton - cabeza, h)
    crop_h_cabeza = alto_cabeza / preset["cabeza_relativa"]
    crop_w_cabeza = crop_h_cabeza * ratio

    # Ancho real de la persona en la foto (parte más ancha: hombros o pelo).
    # El cuadro NUNCA puede ser más ancho que la persona, o quedaría blanco a los
    # lados. Tomamos el menor de los dos anchos: el de la cabeza (carnet) y el de
    # la silueta con leve desborde (0.94 = la persona pasa un 6% los bordes, así
    # siempre los toca). Como las fotos de clientes vienen en tamaños distintos,
    # esto se adapta sola a cada una.
    span = ancho_persona(alpha)
    if span is not None:
        col_izq, col_der = span
        ancho_silueta = col_der - col_izq
        centro_x = (col_izq + col_der) / 2
        crop_w = min(crop_w_cabeza, ancho_silueta * 0.94)
    else:
        crop_w = crop_w_cabeza
        centro_x = cx
    crop_h = crop_w / ratio

    # La caja no puede pasar el borde INFERIOR de la foto: en fotos que ya
    # vienen recortadas tipo carnet la persona toca el borde de abajo y no hay
    # mas cuerpo; lo que faltara se rellenaria de blanco y el torso quedaria
    # flotando sobre una franja blanca (feedback disenadora 2026-07-01).
    # Manteniendo el margen superior, el alto maximo usable es
    # (alto - cabeza) / (1 - margen); si la caja pide mas, se achica con el
    # mismo aspecto (el ancho solo baja: la persona sigue llenando los lados).
    disponible = ((img_rgb.height - cabeza)
                  / max(1e-6, 1.0 - preset["margen_superior"]))
    if crop_h > disponible:
        crop_h = disponible
        crop_w = crop_h * ratio

    # Anclar arriba en el tope del pelo + margen blanco (nunca corta el pelo) y
    # centrar en el eje de la persona para que llene parejo a izquierda y derecha.
    top = cabeza - preset["margen_superior"] * crop_h
    left = int(centro_x - crop_w / 2)
    return left, int(top), int(crop_w), int(crop_h)

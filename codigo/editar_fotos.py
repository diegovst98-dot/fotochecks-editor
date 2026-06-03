import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path


def base_dir():
    # La carpeta base (donde estan config.json, modelo/, salida/):
    #  - empaquetado como .exe: donde esta el .exe.
    #  - como script: la raiz del proyecto. El codigo vive en <raiz>/codigo/,
    #    asi que si corremos desde ahi subimos un nivel para llegar a los datos.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    p = Path(__file__).resolve().parent
    if p.name == "codigo":
        return p.parent
    return p


BASE = base_dir()
ENTRADA = BASE / "entrada"
SALIDA = BASE / "salida"
CONFIG = BASE / "config.json"

# Indicar a rembg donde esta el modelo de IA (carpeta "modelo" junto al .exe),
# para que no intente descargarlo de internet. Debe definirse ANTES de importar
# rembg.
_MODELO_DIR = BASE / "modelo"
if _MODELO_DIR.exists():
    os.environ.setdefault("U2NET_HOME", str(_MODELO_DIR))

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

# rembg (el motor de IA que quita el fondo) es la libreria mas pesada de cargar
# (arrastra numba y scipy, varios segundos). Por eso NO se importa al abrir: se
# carga de forma diferida recien al procesar la primera foto, detras del mensaje
# "Preparando modelo de IA...". Asi la ventana abre casi al instante.


def new_session(*args, **kwargs):
    from rembg import new_session as _new_session
    return _new_session(*args, **kwargs)


EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


# ---------- emparejado de fotos con codigos (Excel) ----------
# CardPresso enlaza cada foto por el codigo en el nombre del archivo. El cliente
# manda las fotos con nombre y apellido; el Excel tiene codigo + nombre. Aqui se
# empareja el nombre del archivo contra el Excel y se devuelve el codigo para
# renombrar la salida. Conservador a proposito: solo empareja cuando esta seguro
# (poner un codigo equivocado en un fotocheck es grave); las dudas se marcan.

def _normalizar(texto):
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[_\-.]+", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _tokens(texto):
    return set(_normalizar(texto).split())


def cargar_codigos(ruta_excel):
    # Lee un Excel de 2 columnas (codigo de empleado, nombre completo) y devuelve
    # una lista de registros. Detecta sola cual columna es el codigo (la que
    # tiene digitos) y descarta encabezados.
    import openpyxl
    wb = openpyxl.load_workbook(ruta_excel, data_only=True)
    ws = wb.active
    registros = []
    for fila in ws.iter_rows(values_only=True):
        if not fila:
            continue
        valores = [c for c in fila if c not in (None, "")]
        if len(valores) < 2:
            continue
        a, b = str(valores[0]).strip(), str(valores[1]).strip()
        if _es_codigo(a) and not _es_codigo(b):
            codigo, nombre = a, b
        elif _es_codigo(b) and not _es_codigo(a):
            codigo, nombre = b, a
        else:
            codigo, nombre = a, b
        if not re.sub(r"[^0-9]", "", codigo):
            continue  # salta encabezado y filas sin codigo numerico
        if not _normalizar(nombre):
            continue
        registros.append({
            "codigo": codigo,
            "nombre": nombre,
            "norm": _normalizar(nombre),
            "tokens": _tokens(nombre),
        })
    return registros


def _es_codigo(v):
    s = str(v).strip()
    digitos = re.sub(r"[^0-9]", "", s)
    # "parece codigo" si es mayormente digitos (ej. 5333467, 12345678, A-102)
    return len(digitos) >= 4 and len(digitos) >= len(re.sub(r"\s", "", s)) - 2


def emparejar(stem, registros):
    # Devuelve (codigo, estado). estado:
    #   ya_codigo  -> el archivo ya venia nombrado con el codigo
    #   exacto     -> nombre del archivo coincide exacto con el Excel
    #   aproximado -> coincide por subconjunto de tokens (>=2 en comun)
    #   ambiguo    -> coincide con varios registros, no se puede decidir
    #   sin_match  -> no se encontro en el Excel
    norm = _normalizar(stem)
    toks = set(norm.split())

    solo_digitos = re.sub(r"[^0-9]", "", stem)
    if solo_digitos and _normalizar(stem) == solo_digitos:
        for r in registros:
            if re.sub(r"[^0-9]", "", r["codigo"]) == solo_digitos:
                return r["codigo"], "ya_codigo"
        return stem.strip(), "ya_codigo"

    exactos = [r for r in registros if r["norm"] == norm or r["tokens"] == toks]
    if len(exactos) == 1:
        return exactos[0]["codigo"], "exacto"
    if len(exactos) > 1:
        return None, "ambiguo"

    candidatos = [r for r in registros
                  if len(toks & r["tokens"]) >= 2
                  and (toks <= r["tokens"] or r["tokens"] <= toks)]
    if len(candidatos) == 1:
        return candidatos[0]["codigo"], "aproximado"
    if len(candidatos) > 1:
        return None, "ambiguo"
    return None, "sin_match"


def _factor_brillo_auto(img, preset):
    # Mide el brillo de la persona (ignora el fondo blanco) y calcula un factor
    # para llevar la mediana a un objetivo. Acotado para no quemar la foto.
    objetivo = preset.get("brillo_auto_objetivo", 180)
    rgb = np.array(img.convert("RGB"), dtype=np.int16)
    gris = np.array(img.convert("L"), dtype=np.float32)
    no_blanco = ~((rgb[:, :, 0] > 245) & (rgb[:, :, 1] > 245) & (rgb[:, :, 2] > 245))
    vals = gris[no_blanco]
    if vals.size < 100:
        return preset.get("brillo", 1.0)
    media = float(np.median(vals))
    if media <= 1:
        return preset.get("brillo", 1.0)
    return max(0.9, min(1.8, objetivo / media))


def pausar():
    try:
        input("\nPresiona ENTER para cerrar...")
    except EOFError:
        pass


def cargar_preset():
    with open(CONFIG, "r", encoding="utf-8") as f:
        data = json.load(f)
    nombre = data.get("preset_activo", "default")
    presets = data.get("presets", {})
    if nombre not in presets:
        raise SystemExit(f"El preset '{nombre}' no existe en config.json")
    p = presets[nombre]
    p["_nombre"] = nombre
    return p


def ruta_cascade():
    # Ubica el archivo del detector de caras de OpenCV, tanto corriendo como
    # script (usa el de cv2) como empaquetado en .exe (lo busca en el bundle).
    nombre = "haarcascade_frontalface_default.xml"
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(Path(sys._MEIPASS) / "recursos" / nombre)
        candidatos.append(Path(sys._MEIPASS) / "cv2" / "data" / nombre)
    candidatos.append(BASE / "recursos" / nombre)
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


# ---------- correcciones de color (automaticas por foto) ----------
# Como las fotos llegan de colores muy distintos (naranjas, rosadas...), un
# ajuste fijo no sirve: cada foto se MIDE y se corrige sola hacia un mismo
# objetivo. Asi un lote variado sale parejo sin tocar foto por foto.

def _corregir_color(img, mask):
    # Neutraliza el tinte (balance de blancos tipo "mundo gris") usando solo los
    # pixeles de la persona, con limites para no matar el tono de piel. El fondo
    # blanco no se toca.
    arr = np.asarray(img).astype(np.float32)
    sel = arr[mask]
    if sel.shape[0] < 50:
        return img
    medias = sel.reshape(-1, 3).mean(axis=0)
    gris = float(medias.mean())
    ganancias = gris / np.clip(medias, 1.0, None)
    ganancias = np.clip(ganancias, 0.85, 1.18)
    corr = np.clip(arr * ganancias, 0, 255)
    arr2 = arr.copy()
    arr2[mask] = corr[mask]  # solo la persona; el fondo blanco queda intacto
    return Image.fromarray(arr2.astype(np.uint8))


def _corregir_saturacion(img, mask, objetivo):
    # Lleva la saturacion promedio de la persona hacia un objetivo (cada foto
    # sube o baja lo necesario). El blanco (saturacion 0) no se ve afectado.
    arr = np.asarray(img).astype(np.float32)
    sel = arr[mask].reshape(-1, 3)
    if sel.shape[0] < 50:
        return img
    mx = sel.max(axis=1)
    mn = sel.min(axis=1)
    s = np.where(mx > 0, (mx - mn) / np.clip(mx, 1, None), 0)
    media = float(s.mean())
    if media < 0.01:
        return img
    factor = float(np.clip(objetivo / media, 0.7, 1.4))
    return ImageEnhance.Color(img).enhance(factor)


def _limpiar_mascara(alpha, fuerza=1.0):
    # Endurece la mascara del recorte para quitar el "cerco" o halo del fondo y
    # los pelos sueltos semitransparentes que sobre blanco se ven como un fleco
    # azulado/gris. Sube el contraste del canal alfa: lo intermedio (el halo) se
    # va a 0 (fondo) o a 255 (persona). 'fuerza' 0..1 = mas o menos agresivo.
    a = np.asarray(alpha).astype(np.float32) / 255.0
    # ventana de transicion: mas angosta = mas duro (corta mas halo y pelitos)
    centro = 0.55
    medio = 0.30 * (1.0 - 0.6 * fuerza)  # fuerza alta -> ventana mas angosta
    lo, hi = centro - medio, centro + medio
    a = np.clip((a - lo) / max(hi - lo, 1e-3), 0.0, 1.0)
    out = Image.fromarray((a * 255).astype(np.uint8))
    return out.filter(ImageFilter.MinFilter(3))  # recorta 1px de borde residual


def _subir_negros(img, piso):
    # Reduce la intensidad del negro: remapea [0..255] -> [piso..255], asi el
    # negro puro no imprime como "mancha" pesada en la Evolis. El blanco se queda
    # en blanco. Es una regla global (problema de la impresora, no de la foto).
    if not piso or piso <= 0:
        return img
    arr = np.asarray(img).astype(np.float32)
    arr = piso + arr * (255.0 - piso) / 255.0
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


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

    # Anclar arriba en el tope del pelo + margen blanco (nunca corta el pelo) y
    # centrar en el eje de la persona para que llene parejo a izquierda y derecha.
    top = cabeza - preset["margen_superior"] * crop_h
    left = int(centro_x - crop_w / 2)
    return left, int(top), int(crop_w), int(crop_h)


def procesar_una(ruta, preset, session, nombre_salida=None):
    from rembg import remove  # carga diferida (ya quedo cargado tras new_session)
    original = Image.open(ruta).convert("RGB")
    sin_fondo = remove(original, session=session)  # RGBA con transparencia

    # Limpiar el borde del recorte: rembg deja un cerco semitransparente (el
    # fondo original asomandose por el pelo fino) que sobre blanco se ve como un
    # halo azulado/gris con pelitos sueltos. Endurecer el alfa lo elimina.
    fuerza = float(preset.get("limpieza_pelo", 1.0))
    alpha = _limpiar_mascara(sin_fondo.split()[-1], fuerza)
    rgb_sin = sin_fondo.convert("RGB")
    sin_fondo = Image.merge("RGBA", (*rgb_sin.split(), alpha))

    fondo = Image.new("RGBA", sin_fondo.size, tuple(preset["color_fondo"]) + (255,))
    compuesta = Image.alpha_composite(fondo, sin_fondo).convert("RGB")

    cara = detectar_cara(compuesta)
    left, top, crop_w, crop_h = caja_encuadre(compuesta, cara, alpha, preset)
    encuadrada = recortar_region(compuesta, left, top, crop_w, crop_h, preset["color_fondo"])
    alpha_rec = recortar_alpha(alpha, left, top, crop_w, crop_h)
    mask = np.asarray(alpha_rec) > 50  # persona vs fondo en el recorte

    # Correcciones de color (cada una se mide en esta foto y se corrige sola)
    if preset.get("color_auto"):
        encuadrada = _corregir_color(encuadrada, mask)
    if preset.get("saturacion_auto"):
        encuadrada = _corregir_saturacion(encuadrada, mask, preset.get("saturacion_objetivo", 0.40))
    encuadrada = _subir_negros(encuadrada, preset.get("piso_negro", 0))

    # Brillo (manual o automatico)
    if preset.get("brillo_auto"):
        factor = _factor_brillo_auto(encuadrada, preset)
    else:
        factor = preset.get("brillo", 1.0)
    if factor != 1.0:
        encuadrada = ImageEnhance.Brightness(encuadrada).enhance(factor)

    ancho_obj, alto_obj = preset["ancho_px"], preset["alto_px"]
    final = encuadrada.resize((ancho_obj, alto_obj), Image.LANCZOS)

    # Aviso de pixelado: si hubo que estirar mucho el recorte (la parte util de
    # la foto tenia pocos pixeles), la salida se vera borrosa.
    escala = max(ancho_obj / max(crop_w, 1), alto_obj / max(crop_h, 1))
    pixelado = escala > 1.5

    fmt = preset["formato_salida"].upper()
    transparente = bool(preset.get("fondo_transparente")) and fmt == "PNG"
    if transparente:
        a = alpha_rec.resize((ancho_obj, alto_obj), Image.LANCZOS)
        final = Image.merge("RGBA", (*final.split(), a))

    ext = ".png" if fmt == "PNG" else ".jpg"
    stem = nombre_salida if nombre_salida else ruta.stem
    destino = SALIDA / (stem + ext)
    if fmt == "JPG" or fmt == "JPEG":
        final.save(destino, "JPEG", quality=95, dpi=(300, 300))
    else:
        final.save(destino, "PNG", dpi=(300, 300))
    return destino, cara is not None, pixelado


def recolectar_fotos():
    # Si se arrastraron fotos o carpetas encima del .exe, vienen como argumentos.
    # Si no, se usan las fotos de la carpeta 'entrada'.
    args = [Path(a) for a in sys.argv[1:]]
    fotos = []
    if args:
        for p in args:
            if p.is_dir():
                fotos += [q for q in sorted(p.iterdir())
                          if q.suffix.lower() in EXTENSIONES]
            elif p.suffix.lower() in EXTENSIONES and p.exists():
                fotos.append(p)
    elif ENTRADA.exists():
        fotos = [p for p in sorted(ENTRADA.iterdir())
                 if p.suffix.lower() in EXTENSIONES]
    return fotos


def main():
    preset = cargar_preset()
    fotos = recolectar_fotos()

    print("=" * 60)
    print(f"  Editor de fotos para fotochecks - DISECOD")
    print(f"  Preset: {preset['_nombre']}  ->  {preset['ancho_px']} x {preset['alto_px']} px")
    print(f"  Brillo: {preset['brillo']}   Fondo: {preset['color_fondo']}")
    print("=" * 60)

    if not fotos:
        print("\nNo hay fotos. Arrastra las fotos (o una carpeta) encima del programa,")
        print("o ponlas en la carpeta 'entrada' y vuelve a ejecutar.")
        pausar()
        return

    SALIDA.mkdir(parents=True, exist_ok=True)
    print(f"\nFotos a procesar: {len(fotos)}\nPreparando modelo de IA...\n")
    session = new_session(preset["modelo_recorte"])

    inicio = time.time()
    ok = 0
    sin_cara = []
    errores = []
    for i, ruta in enumerate(fotos, 1):
        try:
            destino, hubo_cara, _pixelado = procesar_una(ruta, preset, session)
            ok += 1
            marca = "" if hubo_cara else "  (!) sin cara detectada, recorte centrado"
            print(f"[{i}/{len(fotos)}] {ruta.name} -> {destino.name}{marca}")
            if not hubo_cara:
                sin_cara.append(ruta.name)
        except Exception as e:
            errores.append((ruta.name, str(e)))
            print(f"[{i}/{len(fotos)}] ERROR en {ruta.name}: {e}")

    seg = time.time() - inicio
    print("\n" + "=" * 60)
    print(f"  Listas: {ok}/{len(fotos)}  en {seg:.1f}s  ->  carpeta 'salida'")
    if sin_cara:
        print(f"  Revisar (sin cara detectada): {', '.join(sin_cara)}")
    if errores:
        print(f"  Con error: {', '.join(n for n, _ in errores)}")
    print("=" * 60)
    pausar()


if __name__ == "__main__":
    main()

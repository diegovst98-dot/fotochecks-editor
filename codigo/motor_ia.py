# Motor de IA: el modelo que separa a la persona del fondo, y su descarga.
import rutas

# rembg (el motor de IA que quita el fondo) es la libreria mas pesada de cargar
# (arrastra numba y scipy, varios segundos). Por eso NO se importa al abrir: se
# carga de forma diferida recien al procesar la primera foto, detras del mensaje
# "Preparando modelo de IA...". Asi la ventana abre casi al instante.


def new_session(*args, **kwargs):
    from rembg import new_session as _new_session
    return _new_session(*args, **kwargs)


# Modelo "fino": recorta el pelo mechon a mechon (isnet), sin el casco blanco
# que dejaba u2net_human_seg sobre fondos de color. Es el modelo de TODOS los
# dias. No viene en el ZIP original: se descarga UNA sola vez (~180 MB).
MODELO_FINO = "isnet-general-use"

# Modelo "maximo": el mas potente que existe para retratos (BiRefNet). Solo
# para la foto puntual con pelo muy dificil: tarda ~15s por foto en la PC de
# Diego (hasta ~1 min en PCs mas lentas) y pesa ~900 MB en disco.
MODELO_MAXIMO = "birefnet-portrait"

URL_MODELOS = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
# Nombre del archivo EN EL SERVIDOR de rembg (no siempre coincide con el nombre
# local que rembg espera encontrar en modelo/).
ARCHIVO_EN_SERVIDOR = {
    MODELO_FINO: "isnet-general-use.onnx",
    MODELO_MAXIMO: "BiRefNet-portrait-epoch_150.onnx",
}


def _modelo_descargado(nombre):
    return (rutas.MODELO_DIR / (nombre + ".onnx")).exists()


def modelo_fino_descargado():
    return _modelo_descargado(MODELO_FINO)


def modelo_maximo_descargado():
    return _modelo_descargado(MODELO_MAXIMO)


def _descargar_modelo(nombre, minimo_mb, progreso=None):
    # Descarga un modelo con el MISMO mecanismo del lanzador (urllib +
    # certificados de certifi), porque la descarga interna de rembg falla
    # dentro del .exe congelado. Atomica: baja a .tmp, valida el tamano y
    # recien lo pone en su sitio. 'progreso' recibe el porcentaje (0-100).
    import ssl
    import urllib.request
    if _modelo_descargado(nombre):
        return
    rutas.MODELO_DIR.mkdir(parents=True, exist_ok=True)
    destino = rutas.MODELO_DIR / (nombre + ".onnx")
    tmp = destino.with_suffix(".onnx.tmp")
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    archivo = ARCHIVO_EN_SERVIDOR.get(nombre, nombre + ".onnx")
    req = urllib.request.Request(URL_MODELOS + archivo,
                                 headers={"User-Agent": "FotochecksEditor"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r, \
                open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            leido = 0
            ultimo = -1
            while True:
                bloque = r.read(256 * 1024)
                if not bloque:
                    break
                f.write(bloque)
                leido += len(bloque)
                if progreso and total:
                    pct = int(leido * 100 / total)
                    if pct != ultimo:
                        ultimo = pct
                        progreso(pct)
        if tmp.stat().st_size < minimo_mb * 1024 * 1024:
            raise ValueError("descarga incompleta")
        tmp.replace(destino)
    finally:
        if tmp.exists():
            tmp.unlink()


def descargar_modelo_fino(progreso=None):
    _descargar_modelo(MODELO_FINO, 100, progreso)


def sesion_recorte(preset, progreso=None):
    # Devuelve (session, fino). Intenta el modelo fino (descargandolo si hace
    # falta); si falla, cae al modelo clasico del config sin romper nada.
    try:
        descargar_modelo_fino(progreso)
        return new_session(MODELO_FINO), True
    except Exception:
        return new_session(preset["modelo_recorte"]), False


def sesion_maxima(progreso=None):
    # Sesion del modelo de maxima calidad. SIN fallback silencioso: si no se
    # puede descargar, lanza el error para que la interfaz avise claramente
    # (quien pide calidad maxima no quiere otra cosa a escondidas).
    _descargar_modelo(MODELO_MAXIMO, 400, progreso)
    return new_session(MODELO_MAXIMO)

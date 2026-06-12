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
# que dejaba u2net_human_seg sobre fondos de color. No viene en el ZIP original:
# se descarga UNA sola vez (~180 MB, del release oficial de rembg) a la carpeta
# modelo/. Si no se puede descargar (sin internet), se sigue usando el modelo
# clasico de siempre.
MODELO_FINO = "isnet-general-use"
URL_MODELO_FINO = ("https://github.com/danielgatis/rembg/releases/download/"
                   "v0.0.0/" + MODELO_FINO + ".onnx")


def modelo_fino_descargado():
    return (rutas.MODELO_DIR / (MODELO_FINO + ".onnx")).exists()


def descargar_modelo_fino(progreso=None):
    # Descarga el modelo fino con el MISMO mecanismo del lanzador (urllib +
    # certificados de certifi), porque la descarga interna de rembg falla
    # dentro del .exe congelado. Atomica: baja a .tmp, valida el tamano y
    # recien lo pone en su sitio. 'progreso' recibe el porcentaje (0-100).
    import ssl
    import urllib.request
    if modelo_fino_descargado():
        return
    rutas.MODELO_DIR.mkdir(parents=True, exist_ok=True)
    destino = rutas.MODELO_DIR / (MODELO_FINO + ".onnx")
    tmp = destino.with_suffix(".onnx.tmp")
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(URL_MODELO_FINO,
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
        if tmp.stat().st_size < 100 * 1024 * 1024:
            raise ValueError("descarga incompleta")
        tmp.replace(destino)
    finally:
        if tmp.exists():
            tmp.unlink()


def sesion_recorte(preset, progreso=None):
    # Devuelve (session, fino). Intenta el modelo fino (descargandolo si hace
    # falta); si falla, cae al modelo clasico del config sin romper nada.
    try:
        descargar_modelo_fino(progreso)
        return new_session(MODELO_FINO), True
    except Exception:
        return new_session(preset["modelo_recorte"]), False

# Rutas y configuracion del programa: donde viven los archivos y el preset.
# (Modulo base: todos los demas importan de aqui. No importa nada del proyecto.)
import json
import os
import sys
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
CONFIG = BASE / "config.json"

# Indicar a rembg donde esta el modelo de IA (carpeta "modelo" junto al .exe),
# para que no intente descargarlo de internet. Debe definirse ANTES de importar
# rembg.
MODELO_DIR = BASE / "modelo"
if MODELO_DIR.exists():
    os.environ.setdefault("U2NET_HOME", str(MODELO_DIR))

EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


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


def pausar():
    try:
        input("\nPresiona ENTER para cerrar...")
    except EOFError:
        pass

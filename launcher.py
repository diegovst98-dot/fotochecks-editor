"""
Lanzador delgado del Editor de Fotos - DISECOD.

Por que existe: el exe pesa ~330 MB porque incluye Python, las librerias y el
modelo de IA. Eso casi nunca cambia. Lo que SI cambia seguido es el codigo del
programa (app.py / editar_fotos.py), que pesa pocos KB.

Para poder actualizar el programa sin reenviar 330 MB, el codigo NO se hornea
dentro del exe: vive afuera, en la carpeta "codigo/" al lado del exe. Este
lanzador es lo unico compilado; al abrir, carga el codigo desde "codigo/".
Asi una actualizacion futura solo reemplaza esos archivos chicos.

Las librerias pesadas se importan aqui abajo a proposito: asi PyInstaller las
mete dentro del exe (con sus hooks de Tcl/Tk, datos de cv2, etc.), aunque el
codigo real que las usa este afuera.
"""

import os
import sys
import importlib
from pathlib import Path


def base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE = base_dir()
CODIGO = BASE / "codigo"

# --- Actualizacion automatica desde GitHub ---
# El programa revisa al abrir si hay una version nueva del codigo y, si la hay,
# la descarga y reemplaza SOLO la carpeta codigo/ (pocos KB) antes de arrancar.
# Lo pesado (Python, librerias, modelo) vive dentro del exe y no se toca.
USUARIO_REPO = "diegovst98-dot"
NOMBRE_REPO = "fotochecks-editor"
RAMA = "main"
_RAW = "https://raw.githubusercontent.com/%s/%s/%s" % (USUARIO_REPO, NOMBRE_REPO, RAMA)
URL_MANIFEST = _RAW + "/manifest.json"
URL_CODIGO = _RAW + "/codigo"


def _version_local():
    try:
        return int((CODIGO / "version.txt").read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _contexto_ssl():
    # Verificacion de certificados SI o SI: el codigo descargado se EJECUTA, asi
    # que no podemos confiar en una conexion sin validar (riesgo de inyeccion).
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def buscar_actualizacion():
    # Devuelve True si actualizo el codigo. Cualquier error (sin internet,
    # descarga a medias, etc.) => no toca nada y sigue con lo que ya hay.
    import json
    import shutil
    import tempfile
    import urllib.request

    ctx = _contexto_ssl()
    try:
        with urllib.request.urlopen(URL_MANIFEST, timeout=6, context=ctx) as r:
            manifest = json.loads(r.read().decode("utf-8"))
    except Exception:
        return False

    try:
        remota = int(manifest.get("version", 0))
    except Exception:
        return False
    archivos = manifest.get("archivos", [])
    if remota <= _version_local() or not archivos:
        return False

    # Descargar TODO a una carpeta temporal y validar antes de reemplazar, para
    # que una descarga a medias nunca deje el programa roto (cambio atomico).
    tmp = Path(tempfile.mkdtemp(prefix="fotochecks_upd_"))
    try:
        for nombre in archivos:
            with urllib.request.urlopen(URL_CODIGO + "/" + nombre, timeout=20, context=ctx) as r:
                data = r.read()
            if not data:
                return False
            if nombre.endswith(".py"):
                compile(data.decode("utf-8"), nombre, "exec")  # valida que no este corrupto
            (tmp / nombre).write_bytes(data)
        CODIGO.mkdir(parents=True, exist_ok=True)
        for nombre in archivos:
            shutil.copy(tmp / nombre, CODIGO / nombre)
        return True
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# Apuntar rembg al modelo local ANTES de importarlo (evita que busque internet).
_modelo = BASE / "modelo"
if _modelo.exists():
    os.environ.setdefault("U2NET_HOME", str(_modelo))

# --- Forzar que PyInstaller incluya las librerias pesadas en el exe ---
# (el codigo que las usa vive afuera, asi que hay que nombrarlas aqui)
import numpy            # noqa: F401
import cv2              # noqa: F401
import PIL.Image        # noqa: F401
import PIL.ImageEnhance  # noqa: F401
import PIL.ImageFilter  # noqa: F401
import PIL.ImageTk      # noqa: F401
import rembg            # noqa: F401
import onnxruntime      # noqa: F401
import openpyxl         # noqa: F401
import certifi          # noqa: F401
import tkinter          # noqa: F401
import tkinter.ttk      # noqa: F401
import tkinter.filedialog  # noqa: F401
import tkinter.messagebox  # noqa: F401


def main():
    # 1) Revisar e instalar actualizacion ANTES de cargar el codigo (asi el swap
    #    ocurre sin que ningun modulo este cargado: simple y sin conflictos).
    try:
        buscar_actualizacion()
    except Exception:
        pass

    # 2) Cargar el codigo externo desde codigo/ (no esta dentro del exe).
    sys.path.insert(0, str(CODIGO))
    try:
        app = importlib.import_module("app")
    except Exception as e:
        # Si falta la carpeta codigo/ o esta corrupta, avisar en vez de morir mudo.
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror(
                "Editor de Fotos - DISECOD",
                "No se pudo cargar el programa desde la carpeta 'codigo'.\n\n"
                "Detalle: " + str(e))
            r.destroy()
        except Exception:
            print("ERROR cargando codigo/app.py:", e)
        return
    app.main()


if __name__ == "__main__":
    main()

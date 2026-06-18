import json
import logging
import os
import platform
import queue
import shutil
import threading
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from PIL import Image, ImageTk

import editar_fotos as core

EXT = core.EXTENSIONES
MAX_MINIATURAS = 24  # tope de miniaturas a mostrar (lotes grandes serian lentos)

COLOR_FONDO = "#383838"
COLOR_LILA = "#9987F7"
COLOR_LIMA = "#E7F849"
COLOR_TEXTO = "#FFFFFF"
COLOR_ALERTA = "#E74C3C"  # rojo para fotos a revisar

ULTIMO = core.BASE / "ultimo.json"      # recuerda el ultimo tamano usado
CLIENTES = core.BASE / "clientes.json"  # configuracion guardada por cliente
SIN_CLIENTE = "(sin cliente)"
REGISTRO = core.BASE / "registro.log"   # caja negra: bitacora para diagnosticar


def _armar_caja_negra():
    # Bitacora de lo que hace el programa. Rota sola (max ~600 KB en total),
    # y si no se puede escribir (permisos), la app funciona igual sin bitacora.
    # OJO: rotacion MANUAL con logging.FileHandler — logging.handlers NO existe
    # dentro del .exe congelado (leccion v21->v22: el exe solo trae las piezas
    # de Python empacadas al construirlo; un import nuevo puede no estar).
    log = logging.getLogger("editor")
    log.setLevel(logging.INFO)
    if not log.handlers:
        try:
            if REGISTRO.exists() and REGISTRO.stat().st_size > 300_000:
                REGISTRO.replace(REGISTRO.with_suffix(".log.1"))  # archivar
            h = logging.FileHandler(REGISTRO, encoding="utf-8")
            h.setFormatter(logging.Formatter(
                "%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            log.addHandler(h)
        except Exception:
            log.addHandler(logging.NullHandler())
    return log


LOG = _armar_caja_negra()


def _diagnostico(error_txt=""):
    # Reporte tecnico listo para pegar en el chat: version, equipo, el error
    # y los ultimos eventos de la bitacora. Es lo que se copia al portapapeles
    # cuando algo falla, para diagnosticar a distancia sin adivinar.
    lineas = ["=== DIAGNOSTICO - EDITOR DE FOTOS DISECOD ===",
              f"version: {_version()} | equipo: {platform.node()} | "
              f"fecha: {time.strftime('%Y-%m-%d %H:%M')}"]
    if error_txt:
        lineas += ["", "--- ERROR ---", str(error_txt).strip()]
    try:
        cola = REGISTRO.read_text(encoding="utf-8", errors="ignore").splitlines()
        lineas += ["", "--- ULTIMOS EVENTOS ---"] + cola[-40:]
    except Exception:
        pass
    return "\n".join(lineas)


def _version():
    # La version visible en el titulo: clave para soporte remoto ("¿que version
    # tienes?") sin pedirle al usuario que busque archivos.
    try:
        return (Path(__file__).resolve().parent / "version.txt").read_text().strip()
    except Exception:
        return ""


class App:
    def __init__(self, root):
        self.root = root
        try:
            self.preset = core.cargar_preset()
        except Exception:
            self.preset = None
        self.session = None
        self.fino = False         # True si el modelo fino de recorte esta activo
        self.session_max = None   # modelo de maxima calidad (solo si se usa)
        self.session_clasica = None  # 2do modelo (u2net) solo para detectar dudosos
        self.modo_maximo = False  # el lote actual va en calidad maxima
        self.thumbs = []          # referencias a las imagenes (evita que se borren)
        self.cola = queue.Queue()
        self.procesando = False
        self.cancelado = False    # el usuario pidio cortar el proceso en curso
        self.codigos = []         # registros del Excel (codigo + nombre)
        self.ruta_excel = None
        self.resultados_listos = []  # archivos del ultimo lote (para copiarlos)
        self.rev_fotos = []          # fotos elegidas en la pestaña Revisar pedido
        self.resoluciones = {}       # nombre_archivo -> codigo elegido a mano (Fase 2)
        self.calidad_ok = set()      # fotos que el operador perdona por calidad
        self.rev_resultado = None    # ultimo resultado de revisar_pedido (para el reporte)
        self.clientes = self._cargar_clientes()
        self.var_excel = tk.StringVar(
            value="Opcional: las fotos salen con su nombre original.")

        v = _version()
        root.title("Editor de Fotos Fotochecks - DISECOD" + (f"   v{v}" if v else ""))
        LOG.info(f"--- programa abierto: v{v} en {platform.node()} ---")
        # Cualquier error de la interfaz pasa por la caja negra (no se pierde)
        root.report_callback_exception = self._error_interfaz
        root.geometry("960x900")
        root.configure(bg=COLOR_FONDO)
        root.minsize(840, 740)

        cab = tk.Frame(root, bg=COLOR_FONDO)
        cab.pack(fill="x", padx=20, pady=(18, 8))
        tk.Label(cab, text="Editor de Fotos para Fotochecks",
                 bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(cab, text="Quita el fondo, ajusta el brillo y deja el tamano exacto. Todo automatico.",
                 bg=COLOR_FONDO, fg="#CFCFCF",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        # --- Pestañas: cada tarea tiene su espacio, sin amontonar controles ---
        estilo = ttk.Style(root)
        try:
            estilo.theme_use("default")
        except Exception:
            pass
        estilo.configure("TNotebook", background=COLOR_FONDO, borderwidth=0)
        estilo.configure("TNotebook.Tab", font=("Segoe UI", 11, "bold"),
                         padding=(18, 8))
        estilo.map("TNotebook.Tab",
                   background=[("selected", COLOR_LILA), ("!selected", "#4a4a4a")],
                   foreground=[("selected", "#1d1d1d"), ("!selected", "#FFFFFF")])
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="x", padx=20, pady=(4, 0))
        self.tab_fotos = tk.Frame(self.nb, bg=COLOR_FONDO)
        self.tab_revision = tk.Frame(self.nb, bg=COLOR_FONDO)
        self.tab_firmas = tk.Frame(self.nb, bg=COLOR_FONDO)
        self.nb.add(self.tab_fotos, text="Procesar fotos")
        self.nb.add(self.tab_revision, text="Revisar pedido")
        self.nb.add(self.tab_firmas, text="Firmas")

        # --- Cliente (configuracion guardada por cliente recurrente) ---
        fila_cli = tk.Frame(self.tab_fotos, bg=COLOR_FONDO)
        fila_cli.pack(fill="x", padx=20, pady=(10, 2))
        tk.Label(fila_cli, text="Cliente:", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.var_cliente = tk.StringVar(value=SIN_CLIENTE)
        self.combo_cliente = ttk.Combobox(fila_cli, textvariable=self.var_cliente,
                                          state="readonly", width=28,
                                          font=("Segoe UI", 10))
        self.combo_cliente.pack(side="left", padx=(8, 6))
        self.combo_cliente.bind("<<ComboboxSelected>>", self._al_elegir_cliente)
        self._refrescar_clientes()
        self.btn_guardar_cliente = tk.Button(
            fila_cli, text=" Guardar cliente ", command=self.guardar_cliente,
            bg="#5a5a5a", fg=COLOR_TEXTO, activebackground="#6e6e6e",
            font=("Segoe UI", 9), relief="flat", cursor="hand2", padx=8, pady=4)
        self.btn_guardar_cliente.pack(side="left")
        tk.Label(fila_cli, text="Elige un cliente y se aplica su configuracion (medida, fondo, etc.).",
                 bg=COLOR_FONDO, fg="#7a7a7a",
                 font=("Segoe UI", 8)).pack(side="left", padx=(10, 0))

        botones = tk.Frame(self.tab_fotos, bg=COLOR_FONDO)
        botones.pack(fill="x", padx=20, pady=8)
        self.btn_fotos = tk.Button(botones, text="  Elegir fotos  ",
                                   command=self.elegir_fotos,
                                   bg=COLOR_LILA, fg="#1d1d1d",
                                   activebackground="#b3a6fa",
                                   font=("Segoe UI", 13, "bold"),
                                   relief="flat", cursor="hand2",
                                   padx=14, pady=10)
        self.btn_fotos.pack(side="left")
        self.btn_carpeta = tk.Button(botones, text="  Elegir una carpeta  ",
                                     command=self.elegir_carpeta,
                                     bg="#5a5a5a", fg=COLOR_TEXTO,
                                     activebackground="#6e6e6e",
                                     font=("Segoe UI", 11),
                                     relief="flat", cursor="hand2",
                                     padx=12, pady=10)
        self.btn_carpeta.pack(side="left", padx=(10, 0))
        # Para LA foto puntual con pelo muy dificil: modelo de maxima calidad
        # (~2 min por foto, por eso no es el modo normal).
        self.btn_dificil = tk.Button(botones, text="  Foto dificil  ",
                                     command=self.elegir_foto_dificil,
                                     bg="#5a5a5a", fg=COLOR_TEXTO,
                                     activebackground="#6e6e6e",
                                     font=("Segoe UI", 11),
                                     relief="flat", cursor="hand2",
                                     padx=12, pady=10)
        self.btn_dificil.pack(side="left", padx=(10, 0))
        self.btn_abrir = tk.Button(botones, text="  Abrir resultados  ",
                                   command=self.abrir_salida,
                                   bg="#5a5a5a", fg=COLOR_TEXTO,
                                   activebackground="#6e6e6e",
                                   font=("Segoe UI", 11),
                                   relief="flat", cursor="hand2",
                                   padx=12, pady=10)
        self.btn_abrir.pack(side="right")
        # PDF para que el cliente apruebe nombres/codigos ANTES de imprimir.
        self.btn_aprobacion = tk.Button(botones, text="  Hoja de aprobacion (PDF)  ",
                                        command=self.generar_aprobacion,
                                        bg="#5a5a5a", fg=COLOR_TEXTO,
                                        activebackground="#6e6e6e",
                                        font=("Segoe UI", 11),
                                        relief="flat", cursor="hand2",
                                        padx=12, pady=10, state="disabled")
        self.btn_aprobacion.pack(side="right", padx=(0, 10))

        # Tamano de salida editable (en pixeles), por si cada trabajo usa otra
        # medida. Recuerda el ultimo usado (tamano y formato) entre sesiones.
        ultimo = self._cargar_ultimo()
        ancho_def, alto_def = ultimo["ancho"], ultimo["alto"]
        medidas = tk.Frame(self.tab_fotos, bg=COLOR_FONDO)
        medidas.pack(fill="x", padx=20, pady=(2, 4))
        tk.Label(medidas, text="Tamano de salida:", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        vcmd = (root.register(self._solo_digitos), "%P")
        self.var_ancho = tk.StringVar(value=str(ancho_def))
        self.var_alto = tk.StringVar(value=str(alto_def))
        tk.Label(medidas, text="Ancho", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(12, 3))
        tk.Entry(medidas, textvariable=self.var_ancho, width=7, justify="center",
                 validate="key", validatecommand=vcmd).pack(side="left")
        tk.Label(medidas, text="x", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=5)
        tk.Label(medidas, text="Alto", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(6, 3))
        tk.Entry(medidas, textvariable=self.var_alto, width=7, justify="center",
                 validate="key", validatecommand=vcmd).pack(side="left")
        tk.Label(medidas, text="px", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(3, 0))

        # Brillo: factor manual (calibrado para la Evolis) o automatico por foto.
        brillo_def = self.preset.get("brillo", 1.32) if self.preset else 1.32
        self.var_brillo = tk.StringVar(value=str(brillo_def))
        self.var_brillo_auto = tk.BooleanVar(value=False)
        tk.Label(medidas, text="   Brillo", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(18, 3))
        self.entry_brillo = tk.Entry(medidas, textvariable=self.var_brillo, width=6, justify="center")
        self.entry_brillo.pack(side="left")
        tk.Checkbutton(medidas, text="automatico", variable=self.var_brillo_auto,
                       command=self._toggle_brillo, bg=COLOR_FONDO, fg="#CFCFCF",
                       selectcolor="#2b2b2b", activebackground=COLOR_FONDO,
                       activeforeground=COLOR_TEXTO).pack(side="left", padx=(6, 0))
        tk.Label(medidas, text="(recomendado activo)", bg=COLOR_FONDO, fg="#7a7a7a",
                 font=("Segoe UI", 8)).pack(side="left", padx=(2, 0))

        # Formato de salida: PNG (mas calidad, pesa mas) o JPG (mas liviano).
        self.var_formato = tk.StringVar(value=ultimo["formato"])
        tk.Label(medidas, text="   Formato", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(18, 3))
        for f in ("PNG", "JPG"):
            tk.Radiobutton(medidas, text=f, variable=self.var_formato, value=f,
                           bg=COLOR_FONDO, fg="#CFCFCF", selectcolor="#2b2b2b",
                           activebackground=COLOR_FONDO, activeforeground=COLOR_TEXTO).pack(side="left")

        # --- Encuadre y fondo ---
        op = tk.Frame(self.tab_fotos, bg=COLOR_FONDO)
        op.pack(fill="x", padx=20, pady=(2, 4))
        cab_def = self.preset.get("cabeza_relativa", 0.68) if self.preset else 0.68
        tk.Label(op, text="Acercamiento", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(op, text="mas cuerpo", bg=COLOR_FONDO, fg="#9a9a9a",
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 2))
        self.var_zoom = tk.DoubleVar(value=cab_def)
        tk.Scale(op, from_=0.45, to=0.85, resolution=0.01, orient="horizontal",
                 variable=self.var_zoom, showvalue=False, length=150,
                 bg=COLOR_FONDO, fg=COLOR_TEXTO, troughcolor="#2b2b2b",
                 highlightthickness=0, sliderrelief="flat").pack(side="left")
        tk.Label(op, text="rostro grande", bg=COLOR_FONDO, fg="#9a9a9a",
                 font=("Segoe UI", 8)).pack(side="left", padx=(2, 0))
        self.var_fondo = tk.StringVar(value="blanco")
        tk.Label(op, text="    Fondo", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(16, 3))
        for txt, val in (("Blanco", "blanco"), ("Transparente", "transparente")):
            tk.Radiobutton(op, text=txt, variable=self.var_fondo, value=val,
                           bg=COLOR_FONDO, fg="#CFCFCF", selectcolor="#2b2b2b",
                           activebackground=COLOR_FONDO, activeforeground=COLOR_TEXTO).pack(side="left")
        # Auto-mejora: las fotos que salen con recorte DUDOSO (pelo dificil, ropa
        # clara contra pared clara) se rehacen SOLAS con el motor de mas calidad
        # (BiRefNet) dentro del mismo lote. Asi cada foto sale en su mejor version
        # sin apretar nada. Solo la minoria dudosa tarda mas; se puede apagar si
        # hay prisa. Reemplaza al viejo "Calidad maxima a todo el lote" (que
        # forzaba el motor lento en TODAS sin beneficio).
        self.var_auto_mejora = tk.BooleanVar(value=True)
        tk.Checkbutton(op, text="Mejorar las dificiles automaticamente",
                       variable=self.var_auto_mejora, bg=COLOR_FONDO, fg="#CFCFCF",
                       selectcolor="#2b2b2b", activebackground=COLOR_FONDO,
                       activeforeground=COLOR_TEXTO).pack(side="left", padx=(18, 0))
        # Aclaracion: el fondo lo decide el selector Blanco/Transparente de arriba.
        # "Foto dificil" SOLO mejora el recorte (el calado), no cambia el fondo.
        tk.Label(self.tab_fotos,
                 text="Para un PNG sin fondo, marca 'Transparente' arriba. "
                      "'Foto dificil' solo mejora el recorte, no cambia el fondo.",
                 bg=COLOR_FONDO, fg="#7a7a7a",
                 font=("Segoe UI", 8)).pack(anchor="w", padx=20)

        # --- Correccion de color (automatica por foto) + anti-mancha de negros ---
        col = tk.Frame(self.tab_fotos, bg=COLOR_FONDO)
        col.pack(fill="x", padx=20, pady=(2, 4))
        tk.Label(col, text="Color:", bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.var_color_auto = tk.BooleanVar(value=False)
        self.var_sat_auto = tk.BooleanVar(value=False)
        tk.Checkbutton(col, text="Corregir tinte (auto)", variable=self.var_color_auto,
                       bg=COLOR_FONDO, fg="#CFCFCF", selectcolor="#2b2b2b",
                       activebackground=COLOR_FONDO, activeforeground=COLOR_TEXTO).pack(side="left", padx=(8, 0))
        tk.Checkbutton(col, text="Saturacion (auto)", variable=self.var_sat_auto,
                       bg=COLOR_FONDO, fg="#CFCFCF", selectcolor="#2b2b2b",
                       activebackground=COLOR_FONDO, activeforeground=COLOR_TEXTO).pack(side="left", padx=(8, 0))
        self.var_negros = tk.StringVar(value="0")
        tk.Label(col, text="    Reducir negros", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(12, 3))
        tk.Entry(col, textvariable=self.var_negros, width=4, justify="center").pack(side="left")
        tk.Label(col, text="(0-80, 0 = no tocar)", bg=COLOR_FONDO, fg="#7a7a7a",
                 font=("Segoe UI", 8)).pack(side="left", padx=(3, 0))

        # --- Carpeta donde guardar (por defecto, la carpeta del pedido) ---
        self.carpeta_salida = None
        dest = tk.Frame(self.tab_fotos, bg=COLOR_FONDO)
        dest.pack(fill="x", padx=20, pady=(2, 4))
        self.btn_destino = tk.Button(dest, text="  Guardar en...  ",
                                     command=self.elegir_destino, bg="#5a5a5a",
                                     fg=COLOR_TEXTO, activebackground="#6e6e6e",
                                     font=("Segoe UI", 10), relief="flat",
                                     cursor="hand2", padx=10, pady=6)
        self.btn_destino.pack(side="left")
        self.var_destino = tk.StringVar(value="Cada pedido se guarda solo en su carpeta (pedidos > fecha + cliente). Usa 'Guardar en...' solo si quieres otro destino.")
        tk.Label(dest, textvariable=self.var_destino, bg=COLOR_FONDO, fg="#CFCFCF",
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))

        # Excel de codigos (opcional): renombra cada foto al codigo del empleado
        # para que CardPresso la enlace sola.
        excel_row = tk.Frame(self.tab_fotos, bg=COLOR_FONDO)
        excel_row.pack(fill="x", padx=20, pady=(2, 4))
        self.btn_excel = tk.Button(excel_row, text="  Elegir Excel de codigos  ",
                                   command=self.elegir_excel,
                                   bg="#5a5a5a", fg=COLOR_TEXTO,
                                   activebackground="#6e6e6e",
                                   font=("Segoe UI", 10),
                                   relief="flat", cursor="hand2",
                                   padx=10, pady=6)
        self.btn_excel.pack(side="left")
        tk.Label(excel_row, textvariable=self.var_excel, bg=COLOR_FONDO,
                 fg="#CFCFCF", font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))

        # --- Contenido de la pestaña "Revisar pedido" y "Firmas" ---
        self._armar_tab_revision()
        self._armar_tab_firmas()

        self.estado = tk.StringVar(value="Elige las fotos para empezar.")
        tk.Label(root, textvariable=self.estado, bg=COLOR_FONDO, fg=COLOR_LIMA,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=20)

        prog = tk.Frame(root, bg=COLOR_FONDO)
        prog.pack(fill="x", padx=20, pady=(4, 10))
        # Cancelar: corta el proceso en curso sin esperar a que termine todo el
        # lote (se detiene apenas acaba la foto que esta en mano). Solo se
        # habilita mientras hay un proceso corriendo.
        self.btn_cancelar = tk.Button(prog, text="  Cancelar  ",
                                      command=self.cancelar,
                                      bg="#7a3a3a", fg=COLOR_TEXTO,
                                      activebackground="#9a4a4a",
                                      font=("Segoe UI", 10, "bold"),
                                      relief="flat", cursor="hand2",
                                      padx=12, pady=4, state="disabled")
        self.btn_cancelar.pack(side="right", padx=(10, 0))
        self.barra = ttk.Progressbar(prog, mode="determinate")
        self.barra.pack(side="left", fill="x", expand=True)

        # Zona de miniaturas con scroll
        cont = tk.Frame(root, bg="#2b2b2b", highlightthickness=1,
                        highlightbackground="#4a4a4a")
        cont.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        self.canvas = tk.Canvas(cont, bg="#2b2b2b", highlightthickness=0)
        sb = ttk.Scrollbar(cont, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.galeria = tk.Frame(self.canvas, bg="#2b2b2b")
        self.canvas.create_window((0, 0), window=self.galeria, anchor="nw")
        self.galeria.bind("<Configure>",
                          lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        self.col = 0
        self.fila = 0
        self.mostradas = 0

    def _solo_digitos(self, valor):
        return valor == "" or valor.isdigit()

    def _cargar_ultimo(self):
        # Recuerda entre sesiones el tamano y el formato usados la ultima vez.
        ancho_def = self.preset["ancho_px"] if self.preset else 1067
        alto_def = self.preset["alto_px"] if self.preset else 1031
        fmt_def = (self.preset.get("formato_salida", "PNG") if self.preset else "PNG").upper()
        if fmt_def not in ("PNG", "JPG"):
            fmt_def = "PNG"
        d = {"ancho": ancho_def, "alto": alto_def, "formato": fmt_def}
        try:
            with open(ULTIMO, "r", encoding="utf-8") as f:
                g = json.load(f)
            d["ancho"] = int(g.get("ancho", ancho_def))
            d["alto"] = int(g.get("alto", alto_def))
            f2 = str(g.get("formato", fmt_def)).upper()
            if f2 in ("PNG", "JPG"):
                d["formato"] = f2
        except Exception:
            pass
        return d

    def _guardar_ultimo(self, ancho, alto, formato):
        try:
            with open(ULTIMO, "w", encoding="utf-8") as f:
                json.dump({"ancho": ancho, "alto": alto, "formato": formato}, f)
        except Exception:
            pass

    def _toggle_brillo(self):
        # Desactiva el campo manual cuando el brillo es automatico.
        self.entry_brillo.config(state="disabled" if self.var_brillo_auto.get() else "normal")

    def _leer_brillo(self):
        try:
            b = float(self.var_brillo.get().replace(",", "."))
        except (ValueError, TypeError):
            return None
        return b if 0.2 <= b <= 3.0 else None

    def _leer_negros(self):
        try:
            v = int(self.var_negros.get())
        except (ValueError, TypeError):
            return 0
        return max(0, min(80, v))

    def elegir_foto_dificil(self):
        # Reprocesa foto(s) puntuales con el modelo de MAXIMA calidad (BiRefNet).
        if self.procesando:
            return
        rutas_f = filedialog.askopenfilenames(
            title="Elegir la(s) foto(s) con pelo dificil",
            filetypes=[("Imagenes", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"),
                       ("Todos los archivos", "*.*")])
        if not rutas_f:
            return
        fotos = [Path(r) for r in rutas_f]
        aviso = (f"Se procesara(n) {len(fotos)} foto(s) con el modelo de MAXIMA "
                 "calidad, pensado para pelo muy dificil.\n\n"
                 "Tarda bastante mas que el modo normal (hasta un minuto por "
                 "foto). Es normal, no esta colgado.")
        if not core.modelo_maximo_descargado():
            aviso += "\n\nLa primera vez descargara el modelo (~900 MB, una sola vez)."
        if not messagebox.askokcancel("Calidad maxima", aviso):
            return
        self.iniciar(fotos, maxima=True)

    def elegir_destino(self):
        if self.procesando:
            return
        d = filedialog.askdirectory(title="Elegir carpeta donde guardar las fotos")
        if not d:
            return
        self.carpeta_salida = Path(d)
        core.SALIDA = self.carpeta_salida  # "Abrir resultados" apunta aqui ya
        self.var_destino.set("Se guarda en: " + d)
        # Si ya hay un lote procesado, ofrecer copiarlo: el orden natural de
        # mucha gente es procesar primero y elegir la carpeta despues.
        pendientes = [p for p in self.resultados_listos if Path(p).exists()
                      and Path(p).parent != self.carpeta_salida]
        if pendientes and messagebox.askyesno(
                "Copiar lo ya procesado",
                f"Ya procesaste {len(pendientes)} archivo(s) en este momento.\n\n"
                f"¿Los copio tambien a la carpeta que elegiste?\n{d}"):
            copiados = 0
            for p in pendientes:
                try:
                    shutil.copy2(p, self.carpeta_salida / Path(p).name)
                    copiados += 1
                except Exception:
                    pass
            messagebox.showinfo("Listo", f"Copiados {copiados} archivo(s) a:\n{d}")

    def elegir_excel(self):
        if self.procesando:
            return
        ruta = filedialog.askopenfilename(
            title="Elegir Excel de codigos",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Todos los archivos", "*.*")])
        if not ruta:
            return
        try:
            self.codigos = core.cargar_codigos(ruta)
        except Exception as e:
            messagebox.showerror(
                "No se pudo leer el Excel",
                "Revisa que sea un archivo de Excel con dos columnas: "
                "codigo de empleado y nombre completo.\n\n" + str(e))
            return
        if not self.codigos:
            self.var_excel.set("El Excel no tiene codigos validos. Revisa el archivo.")
            return
        self.ruta_excel = ruta
        n = len(self.codigos)
        self.var_excel.set(f"Excel cargado: {n} codigos. Las fotos saldran renombradas.")
        # Mostrar QUE detecto, para que se entienda como funciona (duda de Mirza).
        ejemplos = "\n".join("   %s  =  %s" % (r["codigo"], r["nombre"])
                             for r in self.codigos[:3])
        messagebox.showinfo(
            "Excel cargado",
            "Lei %d empleados del Excel.\n\n"
            "Detecte sola la columna del CODIGO (la de numeros/DNI) y la del "
            "NOMBRE.\n\nEjemplos:\n%s\n\n"
            "Como funciona: el programa toma el NOMBRE DEL ARCHIVO de cada foto, "
            "lo busca en la columna de nombres y guarda la foto con su codigo "
            "(para que CardPresso la enlace).\n"
            "- Las fotos que ya vienen nombradas con el codigo/DNI se respetan.\n"
            "- Las que no encuentre con seguridad salen con su nombre original y "
            "marcadas en rojo." % (n, ejemplos))

    def _leer_medidas(self):
        # Devuelve (ancho, alto) validos o None si el diseñador escribio algo raro.
        try:
            ancho = int(self.var_ancho.get())
            alto = int(self.var_alto.get())
        except (ValueError, TypeError):
            return None
        if not (50 <= ancho <= 10000 and 50 <= alto <= 10000):
            return None
        return ancho, alto

    # ---------- elegir fotos ----------
    def _confirmar_maxima(self, n):
        # Aviso de tiempo (y descarga la 1a vez) cuando se pide calidad maxima
        # para todo un lote: BiRefNet tarda hasta ~1 min por foto.
        aviso = (f"Procesaras {n} foto(s) en CALIDAD MAXIMA (BiRefNet). El recorte "
                 "sale impecable hasta en ropa clara, pero tarda mucho mas: "
                 "hasta ~1 minuto por foto. Es normal, no esta colgado.")
        if not core.modelo_maximo_descargado():
            aviso += "\n\nLa primera vez descargara el modelo (~900 MB, una sola vez)."
        return messagebox.askokcancel("Calidad maxima", aviso)

    def _expandir_pdfs(self, rutas):
        # Reemplaza cualquier PDF de la seleccion por la(s) foto(s) que trae
        # adentro (1 por pagina). Si el .exe aun no trae la libreria de PDF,
        # avisa y procesa el resto. PDF dañado se ignora en silencio.
        rutas = [Path(r) for r in rutas]
        if not any(r.suffix.lower() == ".pdf" for r in rutas):
            return rutas
        if not core.pdf_disponible():
            messagebox.showinfo(
                "PDF aun no disponible",
                "Este programa todavia no abre archivos PDF (falta una "
                "actualizacion del .exe). Pideselo al cliente en JPG o PNG.\n\n"
                "Sigo con el resto de las fotos.")
            return [r for r in rutas if r.suffix.lower() != ".pdf"]
        temp = core.BASE / "_pdf_temp"
        shutil.rmtree(temp, ignore_errors=True)
        expandidas = []
        for r in rutas:
            if r.suffix.lower() == ".pdf":
                expandidas.extend(core.pdf_a_imagenes(r, temp))
            else:
                expandidas.append(r)
        return expandidas

    def elegir_fotos(self):
        if self.procesando:
            return
        rutas = filedialog.askopenfilenames(
            title="Elegir fotos (acepta tambien PDF)",
            filetypes=[("Imagenes y PDF", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.pdf"),
                       ("Todos los archivos", "*.*")])
        if rutas:
            fotos = self._expandir_pdfs(rutas)
            if not fotos:
                return
            self.iniciar(fotos)

    def elegir_carpeta(self):
        if self.procesando:
            return
        d = filedialog.askdirectory(title="Elegir carpeta con fotos")
        if d:
            items = [q for q in sorted(Path(d).iterdir())
                     if q.suffix.lower() in EXT or q.suffix.lower() == ".pdf"]
            fotos = self._expandir_pdfs(items)
            self.iniciar(fotos)

    def abrir_salida(self):
        try:
            core.SALIDA.mkdir(parents=True, exist_ok=True)
            os.startfile(core.SALIDA)
        except Exception:
            pass

    # ---------- firmas ----------
    def elegir_firmas(self):
        if self.procesando:
            return
        rutas = filedialog.askopenfilenames(
            title="Elegir firmas (escaneo o foto, tinta oscura sobre papel claro)",
            filetypes=[("Imagenes", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"),
                       ("Todos los archivos", "*.*")])
        if not rutas:
            return
        firmas = [Path(r) for r in rutas]
        cli = self.var_cliente.get()
        core.SALIDA = self.carpeta_salida or core.carpeta_pedido(
            "" if cli == SIN_CLIENTE else cli)
        self.resultados_listos = []
        self.limpiar_galeria()
        self.procesando = True
        self.cancelado = False
        self._activar_botones(False)
        self._activar_cancelar(True)
        self.barra.config(maximum=len(firmas), value=0)
        self.estado.set("Procesando firmas...")
        threading.Thread(target=self.worker_firmas,
                         args=(firmas, self.var_firma_color.get()),
                         daemon=True).start()
        self.root.after(100, self.revisar_cola)

    # ---------- pestañas nuevas ----------
    def _armar_tab_revision(self):
        t = self.tab_revision
        tk.Label(t, text="Revisa lo que mando el cliente ANTES de producir: detecta fotos "
                         "faltantes, borrosas o que no cruzan con su lista,",
                 bg=COLOR_FONDO, fg="#CFCFCF", font=("Segoe UI", 10)).pack(anchor="w", padx=20, pady=(12, 0))
        tk.Label(t, text="y arma EL MENSAJE listo para pedirle todo de una sola vez por WhatsApp.",
                 bg=COLOR_FONDO, fg="#CFCFCF", font=("Segoe UI", 10)).pack(anchor="w", padx=20)

        fila1 = tk.Frame(t, bg=COLOR_FONDO)
        fila1.pack(fill="x", padx=20, pady=(10, 4))
        tk.Label(fila1, text="1.", bg=COLOR_FONDO, fg=COLOR_LIMA,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 8))
        self.btn_rev_fotos = tk.Button(fila1, text="  Elegir las fotos del cliente  ",
                                       command=self.elegir_fotos_revision,
                                       bg=COLOR_LILA, fg="#1d1d1d",
                                       activebackground="#b3a6fa",
                                       font=("Segoe UI", 11, "bold"),
                                       relief="flat", cursor="hand2", padx=12, pady=8)
        self.btn_rev_fotos.pack(side="left")
        self.btn_rev_carpeta = tk.Button(fila1, text="  o una carpeta  ",
                                         command=self.elegir_carpeta_revision,
                                         bg="#5a5a5a", fg=COLOR_TEXTO,
                                         activebackground="#6e6e6e",
                                         font=("Segoe UI", 10), relief="flat",
                                         cursor="hand2", padx=10, pady=8)
        self.btn_rev_carpeta.pack(side="left", padx=(8, 0))
        self.var_rev = tk.StringVar(value="Aun no eliges fotos.")
        tk.Label(fila1, textvariable=self.var_rev, bg=COLOR_FONDO, fg="#CFCFCF",
                 font=("Segoe UI", 9)).pack(side="left", padx=(12, 0))

        fila2 = tk.Frame(t, bg=COLOR_FONDO)
        fila2.pack(fill="x", padx=20, pady=4)
        tk.Label(fila2, text="2.", bg=COLOR_FONDO, fg=COLOR_LIMA,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 8))
        self.btn_rev_excel = tk.Button(fila2, text="  Elegir Excel del personal (opcional)  ",
                                       command=self.elegir_excel,
                                       bg="#5a5a5a", fg=COLOR_TEXTO,
                                       activebackground="#6e6e6e",
                                       font=("Segoe UI", 10), relief="flat",
                                       cursor="hand2", padx=10, pady=8)
        self.btn_rev_excel.pack(side="left")
        tk.Label(fila2, textvariable=self.var_excel, bg=COLOR_FONDO, fg="#CFCFCF",
                 font=("Segoe UI", 9)).pack(side="left", padx=(12, 0))

        fila3 = tk.Frame(t, bg=COLOR_FONDO)
        fila3.pack(fill="x", padx=20, pady=4)
        tk.Label(fila3, text="3.", bg=COLOR_FONDO, fg=COLOR_LIMA,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 8))
        self.btn_revisar = tk.Button(fila3, text="  REVISAR PEDIDO  ",
                                     command=self.revisar_pedido,
                                     bg=COLOR_LIMA, fg="#1d1d1d",
                                     activebackground="#eefb7a",
                                     font=("Segoe UI", 12, "bold"),
                                     relief="flat", cursor="hand2", padx=16, pady=8)
        self.btn_revisar.pack(side="left")
        self.btn_copiar = tk.Button(fila3, text="  Copiar mensaje para WhatsApp  ",
                                    command=self.copiar_mensaje,
                                    bg="#5a5a5a", fg=COLOR_TEXTO,
                                    activebackground="#6e6e6e",
                                    font=("Segoe UI", 11), relief="flat",
                                    cursor="hand2", padx=12, pady=8, state="disabled")
        self.btn_copiar.pack(side="left", padx=(10, 0))
        self.btn_reporte = tk.Button(fila3, text="  Descargar reporte  ",
                                     command=self.descargar_reporte,
                                     bg="#5a5a5a", fg=COLOR_TEXTO,
                                     activebackground="#6e6e6e",
                                     font=("Segoe UI", 10), relief="flat",
                                     cursor="hand2", padx=12, pady=8, state="disabled")
        self.btn_reporte.pack(side="left", padx=(8, 0))

        marco = tk.Frame(t, bg="#2b2b2b", highlightthickness=1,
                         highlightbackground="#4a4a4a")
        marco.pack(fill="x", padx=20, pady=(6, 12))
        self.txt_revision = tk.Text(marco, height=8, bg="#2b2b2b", fg="#EAEAEA",
                                    insertbackground="#EAEAEA", wrap="word",
                                    font=("Segoe UI", 10), relief="flat", padx=8, pady=6)
        self.txt_revision.pack(fill="x")
        self.txt_revision.insert("1.0", "Aqui aparecera el mensaje para el cliente. "
                                        "Puedes editarlo antes de copiarlo.")

    def _armar_tab_firmas(self):
        t = self.tab_firmas
        tk.Label(t, text="Convierte firmas escaneadas o fotografiadas en tinta de un "
                         "solo color con fondo transparente, listas para el carnet.",
                 bg=COLOR_FONDO, fg="#CFCFCF", font=("Segoe UI", 10)).pack(anchor="w", padx=20, pady=(14, 0))
        tk.Label(t, text="Sirve cualquier firma con tinta oscura sobre papel claro: "
                         "salen recortadas al trazo, en PNG.",
                 bg=COLOR_FONDO, fg="#CFCFCF", font=("Segoe UI", 10)).pack(anchor="w", padx=20)
        # Color del trazo: negro (lo normal) o blanco para diseños oscuros.
        self.var_firma_color = tk.StringVar(value="negro")
        fila_color = tk.Frame(t, bg=COLOR_FONDO)
        fila_color.pack(anchor="w", padx=20, pady=(10, 0))
        tk.Label(fila_color, text="Color de la firma:", bg=COLOR_FONDO,
                 fg=COLOR_TEXTO, font=("Segoe UI", 10, "bold")).pack(side="left")
        for txt, val in (("Negra (para fondo claro)", "negro"),
                         ("Blanca (para fondo oscuro)", "blanco")):
            tk.Radiobutton(fila_color, text=txt, variable=self.var_firma_color,
                           value=val, bg=COLOR_FONDO, fg="#CFCFCF",
                           selectcolor="#2b2b2b", activebackground=COLOR_FONDO,
                           activeforeground=COLOR_TEXTO).pack(side="left", padx=(8, 0))
        self.btn_firma = tk.Button(t, text="  Elegir firmas...  ",
                                   command=self.elegir_firmas,
                                   bg=COLOR_LILA, fg="#1d1d1d",
                                   activebackground="#b3a6fa",
                                   font=("Segoe UI", 13, "bold"),
                                   relief="flat", cursor="hand2",
                                   padx=14, pady=10)
        self.btn_firma.pack(anchor="w", padx=20, pady=14)
        tk.Label(t, text="Se guardan en la misma carpeta que las fotos (boton "
                         "'Guardar en...' de la pestaña Procesar fotos).",
                 bg=COLOR_FONDO, fg="#7a7a7a", font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 12))

    # ---------- clientes (configuracion guardada) ----------
    def _cargar_clientes(self):
        try:
            with open(CLIENTES, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _refrescar_clientes(self):
        self.combo_cliente["values"] = [SIN_CLIENTE] + sorted(self.clientes)

    def _al_elegir_cliente(self, _evento=None):
        c = self.clientes.get(self.var_cliente.get())
        if not c:
            return
        self.var_ancho.set(str(c.get("ancho", self.var_ancho.get())))
        self.var_alto.set(str(c.get("alto", self.var_alto.get())))
        if c.get("formato") in ("PNG", "JPG"):
            self.var_formato.set(c["formato"])
        if c.get("fondo") in ("blanco", "transparente"):
            self.var_fondo.set(c["fondo"])
        if "zoom" in c:
            self.var_zoom.set(float(c["zoom"]))
        if "brillo" in c:
            self.var_brillo.set(str(c["brillo"]))
        self.var_brillo_auto.set(bool(c.get("brillo_auto", False)))
        self._toggle_brillo()
        self.var_color_auto.set(bool(c.get("color_auto", False)))
        self.var_sat_auto.set(bool(c.get("sat_auto", False)))
        self.var_negros.set(str(c.get("negros", "0")))
        self.estado.set(f"Configuracion de '{self.var_cliente.get()}' aplicada.")

    def guardar_cliente(self):
        actual = self.var_cliente.get()
        nombre = simpledialog.askstring(
            "Guardar cliente", "Nombre del cliente:",
            initialvalue="" if actual == SIN_CLIENTE else actual, parent=self.root)
        if not nombre or not nombre.strip():
            return
        nombre = nombre.strip()
        self.clientes[nombre] = {
            "ancho": self.var_ancho.get(), "alto": self.var_alto.get(),
            "formato": self.var_formato.get(), "fondo": self.var_fondo.get(),
            "zoom": round(float(self.var_zoom.get()), 2),
            "brillo": self.var_brillo.get(),
            "brillo_auto": self.var_brillo_auto.get(),
            "color_auto": self.var_color_auto.get(),
            "sat_auto": self.var_sat_auto.get(),
            "negros": self.var_negros.get(),
        }
        try:
            with open(CLIENTES, "w", encoding="utf-8") as f:
                json.dump(self.clientes, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Error", "No se pudo guardar: " + str(e))
            return
        self._refrescar_clientes()
        self.var_cliente.set(nombre)
        self.estado.set(f"Cliente '{nombre}' guardado con la configuracion actual.")

    # ---------- revision previa del pedido ----------
    def elegir_fotos_revision(self):
        if self.procesando:
            return
        rutas = filedialog.askopenfilenames(
            title="Elegir las fotos que mando el cliente",
            filetypes=[("Imagenes", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"),
                       ("Todos los archivos", "*.*")])
        if rutas:
            self.rev_fotos = [Path(r) for r in rutas]
            self.var_rev.set(f"{len(self.rev_fotos)} foto(s) elegidas.")

    def elegir_carpeta_revision(self):
        if self.procesando:
            return
        d = filedialog.askdirectory(title="Elegir la carpeta con las fotos del cliente")
        if d:
            self.rev_fotos = [q for q in sorted(Path(d).iterdir())
                              if q.suffix.lower() in EXT]
            self.var_rev.set(f"{len(self.rev_fotos)} foto(s) en la carpeta.")

    def revisar_pedido(self):
        if self.procesando:
            return
        if not self.rev_fotos:
            messagebox.showwarning("Faltan fotos",
                                   "Primero elige las fotos que mando el cliente (paso 1).")
            return
        self.limpiar_galeria()
        self.btn_copiar.config(state="disabled")
        self.procesando = True
        self._activar_botones(False)
        self.barra.config(maximum=len(self.rev_fotos), value=0)
        self.estado.set(f"Revisando {len(self.rev_fotos)} fotos...")
        threading.Thread(target=self.worker_revision,
                         args=(list(self.rev_fotos),), daemon=True).start()
        self.root.after(100, self.revisar_cola)

    def worker_revision(self, fotos):
        try:
            rev = core.revisar_fotos(fotos, self.codigos or None,
                                     progreso=lambda i: self.cola.put(("rev_prog", i)))
            self.cola.put(("rev_fin", rev, [str(f) for f in fotos]))
        except Exception:
            self.cola.put(("fatal", traceback.format_exc()))

    def copiar_mensaje(self):
        texto = self.txt_revision.get("1.0", "end").strip()
        if not texto:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(texto)
        self.estado.set("Mensaje copiado. Pegalo en el chat del cliente con Ctrl+V.")

    def descargar_reporte(self):
        # Guarda un CSV con el detalle de la ultima revision (respaldo/auditoria).
        if not self.rev_resultado:
            return
        ruta = filedialog.asksaveasfilename(
            title="Guardar reporte de revision", defaultextension=".csv",
            initialfile="reporte_revision.csv",
            filetypes=[("CSV (Excel)", "*.csv")])
        if not ruta:
            return
        try:
            core.reporte_csv(self.rev_resultado, ruta)
        except Exception as e:
            messagebox.showerror("No se pudo guardar el reporte", str(e))
            return
        self.estado.set("Reporte guardado: " + ruta)
        try:
            os.startfile(ruta)
        except Exception:
            pass

    def _resolver_confirmaciones(self, rev):
        # Dialogo modal (Fase 2): para cada caso "por confirmar" (un parecido o
        # varios candidatos), el operador elige la persona correcta o "Ninguno".
        # Llena self.resoluciones y aplica las decisiones sobre 'rev', para que el
        # mensaje al cliente no pida fotos que en realidad ya tenemos (typos).
        casos = rev.get("por_confirmar", [])
        calidad = rev.get("por_calidad", [])
        if not casos and not calidad:
            return
        win = tk.Toplevel(self.root)
        win.title("Revisar antes de armar el mensaje")
        win.configure(bg=COLOR_FONDO)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text="Resuelve esto antes de mandarle el mensaje al cliente:",
                 bg=COLOR_FONDO, fg=COLOR_TEXTO, font=("Segoe UI", 11, "bold"),
                 wraplength=560, justify="left").pack(anchor="w", padx=16, pady=(14, 8))

        cont = tk.Frame(win, bg=COLOR_FONDO)
        cont.pack(fill="both", expand=True, padx=8)
        canvas = tk.Canvas(cont, bg=COLOR_FONDO, highlightthickness=0, height=380, width=600)
        sb = ttk.Scrollbar(cont, orient="vertical", command=canvas.yview)
        marco = tk.Frame(canvas, bg=COLOR_FONDO)
        marco.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=marco, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        elecciones = {}  # nombre_archivo -> StringVar(codigo o "")
        if casos:
            tk.Label(marco, text="NOMBRES POR CONFIRMAR", bg=COLOR_FONDO,
                     fg=COLOR_LIMA, font=("Segoe UI", 9, "bold")).pack(
                         anchor="w", padx=6, pady=(4, 0))
        for caso in casos:
            nom = caso["nombre"]
            etiqueta = ("¿Es esta persona?" if caso.get("estado") == "sugerencia"
                        else "¿Cuál de estas es?")
            blq = tk.Frame(marco, bg="#2b2b2b", highlightthickness=1,
                           highlightbackground="#4a4a4a")
            blq.pack(fill="x", expand=True, padx=6, pady=5)
            tk.Label(blq, text=nom, bg="#2b2b2b", fg=COLOR_LIMA,
                     font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
            tk.Label(blq, text=etiqueta, bg="#2b2b2b", fg="#CFCFCF",
                     font=("Segoe UI", 9)).pack(anchor="w", padx=8)
            var = tk.StringVar(value="")
            for r in caso.get("candidatos", []):
                det = r.get("detalle") or ""
                txt = f'{r["nombre"]}  ·  DNI {r["codigo"]}' + (f'  ·  {det}' if det else "")
                tk.Radiobutton(blq, text=txt, variable=var, value=r["codigo"],
                               bg="#2b2b2b", fg=COLOR_TEXTO, selectcolor="#1d1d1d",
                               activebackground="#2b2b2b", activeforeground=COLOR_TEXTO,
                               font=("Segoe UI", 10), anchor="w").pack(anchor="w", padx=16)
            tk.Radiobutton(blq, text="Ninguno (lo dejo sin asignar)", variable=var,
                           value="", bg="#2b2b2b", fg="#CFCFCF", selectcolor="#1d1d1d",
                           activebackground="#2b2b2b", activeforeground=COLOR_TEXTO,
                           font=("Segoe UI", 9), anchor="w").pack(anchor="w", padx=16, pady=(0, 6))
            elecciones[nom] = var

        forgive = {}  # nombre_archivo -> BooleanVar (True = la foto va igual)
        if calidad:
            tk.Label(marco, text="FOTOS MARCADAS POR CALIDAD", bg=COLOR_FONDO,
                     fg=COLOR_LIMA, font=("Segoe UI", 9, "bold")).pack(
                         anchor="w", padx=6, pady=(10, 0))
            for c in calidad:
                nom = c["nombre"]
                blq = tk.Frame(marco, bg="#2b2b2b", highlightthickness=1,
                               highlightbackground="#4a4a4a")
                blq.pack(fill="x", expand=True, padx=6, pady=4)
                tk.Label(blq, text=f'{nom}  ({", ".join(c["problemas"])})',
                         bg="#2b2b2b", fg="#CFCFCF", font=("Segoe UI", 9),
                         wraplength=540, justify="left").pack(anchor="w", padx=8, pady=(6, 0))
                bv = tk.BooleanVar(value=False)
                tk.Checkbutton(blq, text="Esta foto va igual (no pedirla de nuevo)",
                               variable=bv, bg="#2b2b2b", fg=COLOR_TEXTO,
                               selectcolor="#1d1d1d", activebackground="#2b2b2b",
                               activeforeground=COLOR_TEXTO, font=("Segoe UI", 9)).pack(
                                   anchor="w", padx=12, pady=(0, 6))
                forgive[nom] = bv

        def aplicar():
            self.resoluciones = {n: v.get() for n, v in elecciones.items() if v.get()}
            self.calidad_ok = {n for n, v in forgive.items() if v.get()}
            win.destroy()

        barra = tk.Frame(win, bg=COLOR_FONDO)
        barra.pack(fill="x", padx=16, pady=12)
        tk.Button(barra, text="  Aplicar  ", command=aplicar, bg=COLOR_LIMA,
                  fg="#1d1d1d", activebackground="#eefb7a", font=("Segoe UI", 11, "bold"),
                  relief="flat", cursor="hand2", padx=14, pady=6).pack(side="right")
        tk.Button(barra, text="  Omitir  ", command=win.destroy, bg="#5a5a5a",
                  fg=COLOR_TEXTO, activebackground="#6e6e6e", font=("Segoe UI", 10),
                  relief="flat", cursor="hand2", padx=12, pady=6).pack(side="right", padx=(0, 8))

        win.update_idletasks()
        win.geometry(f"+{self.root.winfo_rootx() + 60}+{self.root.winfo_rooty() + 60}")
        self.root.wait_window(win)
        if self.resoluciones or self.calidad_ok:
            core.aplicar_resoluciones(rev, self.resoluciones, self.calidad_ok)

    def _avisar_dnis(self, alertas):
        # Aviso INTERNO (no va al cliente): DNIs del Excel que se ven raros
        # (ceros perdidos, letras, longitudes fuera de lo normal).
        if not alertas:
            return
        top = alertas[:20]
        lineas = [f"- {nom}: {cod}  ->  {mot}" for cod, nom, mot in top]
        extra = f"\n...y {len(alertas) - len(top)} mas." if len(alertas) > len(top) else ""
        messagebox.showwarning(
            "Revisa estos DNIs del Excel",
            "Estos documentos se ven raros. Revisa el Excel antes de imprimir "
            "(el editor NO los corrige solo):\n\n" + "\n".join(lineas) + extra)

    # ---------- hoja de aprobacion ----------
    def generar_aprobacion(self):
        if self.procesando or not self.resultados_listos:
            return
        archivos = [Path(p) for p in self.resultados_listos if Path(p).exists()]
        if not archivos:
            messagebox.showwarning("Sin lote", "Primero procesa un lote de fotos.")
            return
        self.procesando = True
        self._activar_botones(False)
        self.estado.set("Generando hoja de aprobacion...")
        threading.Thread(target=self.worker_aprobacion,
                         args=(archivos,), daemon=True).start()
        self.root.after(100, self.revisar_cola)

    def worker_aprobacion(self, archivos):
        try:
            cliente = self.var_cliente.get()
            cliente = "" if cliente == SIN_CLIENTE else cliente
            limpio = "".join(c for c in cliente if c.isalnum() or c in " -_").strip()
            nombre = "aprobacion" + (("_" + limpio.replace(" ", "_")) if limpio else "")
            destino = core.SALIDA / f"{nombre}_{time.strftime('%Y-%m-%d_%H%M')}.pdf"
            nombres = ({r["codigo"]: r["nombre"] for r in self.codigos}
                       if self.codigos else None)
            pdf = core.hoja_aprobacion(archivos, destino, cliente, nombres)
            self.cola.put(("pdf_listo", str(pdf)))
        except Exception:
            self.cola.put(("fatal", traceback.format_exc()))

    def worker_firmas(self, firmas, color="negro"):
        # Las firmas no usan la IA: salen al toque (umbral por luminosidad).
        try:
            core.SALIDA.mkdir(parents=True, exist_ok=True)
            ok = 0
            fallas = []
            for i, ruta in enumerate(firmas, 1):
                if self.cancelado:
                    break
                try:
                    destino = core.procesar_firma(ruta, color=color)
                    ok += 1
                    self.cola.put(("una", i, str(destino), False))
                except Exception as e:
                    fallas.append(f"{ruta.name}: {e}")
                    LOG.info(f"firma fallo {ruta.name}:\n" + traceback.format_exc())
                    self.cola.put(("error_una", i, str(e)))
            self.cola.put(("fin_firmas", ok, len(firmas), fallas))
        except Exception:
            self.cola.put(("fatal", traceback.format_exc()))

    # ---------- procesar ----------
    def iniciar(self, fotos, maxima=False):
        self.modo_maximo = maxima
        # La auto-mejora de las dudosas solo aplica en modo normal (en "Foto
        # dificil" el lote YA va con el motor de maxima calidad).
        self.auto_mejora = self.var_auto_mejora.get() and not maxima
        fotos = [f for f in fotos if f.suffix.lower() in EXT and f.exists()]
        if not fotos:
            messagebox.showwarning("Sin fotos",
                                   "No se encontraron imagenes validas.")
            return
        medidas = self._leer_medidas()
        if medidas is None:
            messagebox.showwarning(
                "Tamano invalido",
                "Escribe un Ancho y un Alto validos en pixeles\n(entre 50 y 10000, por ejemplo 1067 x 1031).")
            return
        brillo = self._leer_brillo()
        if brillo is None and not self.var_brillo_auto.get():
            messagebox.showwarning(
                "Brillo invalido",
                "Escribe un brillo valido (por ejemplo 1.32) o marca 'automatico'.")
            return
        if self.preset is None:
            try:
                self.preset = core.cargar_preset()
            except Exception as e:
                messagebox.showerror("Error", str(e))
                return
        self.preset["ancho_px"], self.preset["alto_px"] = medidas
        self.preset["brillo_auto"] = self.var_brillo_auto.get()
        if brillo is not None:
            self.preset["brillo"] = brillo
        # Encuadre y fondo
        self.preset["cabeza_relativa"] = float(self.var_zoom.get())
        transparente = (self.var_fondo.get() == "transparente")
        if transparente:
            self.var_formato.set("PNG")  # la transparencia solo existe en PNG
        self.preset["formato_salida"] = self.var_formato.get()
        self.preset["fondo_transparente"] = transparente
        # Color
        self.preset["color_auto"] = self.var_color_auto.get()
        self.preset["saturacion_auto"] = self.var_sat_auto.get()
        self.preset["piso_negro"] = self._leer_negros()
        # Carpeta destino: la elegida con "Guardar en...", o la carpeta propia
        # del pedido (pedidos/<fecha> <cliente>) para que cada trabajo quede
        # junto y ordenado en vez de mezclarse en una sola bolsa.
        cli = self.var_cliente.get()
        core.SALIDA = self.carpeta_salida or core.carpeta_pedido(
            "" if cli == SIN_CLIENTE else cli)
        self.resultados_listos = []
        self._guardar_ultimo(medidas[0], medidas[1], self.var_formato.get())
        self.limpiar_galeria()
        self.procesando = True
        self.cancelado = False
        self._activar_botones(False)
        self._activar_cancelar(True)
        self.barra.config(maximum=len(fotos), value=0)
        if maxima:
            if self.session_max is None and not core.modelo_maximo_descargado():
                self.estado.set("Descargando el modelo de MAXIMA calidad (una "
                                "sola vez, ~900 MB). Puede tardar varios minutos...")
            else:
                self.estado.set("Preparando el modelo de maxima calidad...")
        elif self.session is None and not core.modelo_fino_descargado():
            self.estado.set("Mejorando el recorte de pelo: descargando el nuevo "
                            "modelo (UNA sola vez, ~180 MB). Puede tardar...")
        else:
            self.estado.set("Preparando modelo de IA...")
        LOG.info(("CALIDAD MAXIMA | " if maxima else "") +
                 f"lote: {len(fotos)} fotos | fondo {self.var_fondo.get()} | "
                 f"formato {self.var_formato.get()} | cliente {self.var_cliente.get()} | "
                 f"excel {'si' if self.codigos else 'no'} | destino {core.SALIDA}")
        threading.Thread(target=self.worker, args=(fotos,), daemon=True).start()
        self.root.after(100, self.revisar_cola)

    def _activar_botones(self, activo):
        estado = "normal" if activo else "disabled"
        for b in (self.btn_fotos, self.btn_carpeta, self.btn_firma,
                  self.btn_dificil, self.btn_excel, self.btn_destino,
                  self.btn_rev_fotos, self.btn_rev_carpeta, self.btn_rev_excel,
                  self.btn_revisar, self.btn_guardar_cliente):
            b.config(state=estado)
        self.combo_cliente.config(state="readonly" if activo else "disabled")
        # La hoja de aprobacion solo tiene sentido con un lote ya procesado.
        self.btn_aprobacion.config(
            state="normal" if (activo and self.resultados_listos) else "disabled")

    def worker(self, fotos):
        try:
            if self.preset is None:
                self.preset = core.cargar_preset()
            if self.modo_maximo:
                # Modelo de MAXIMA calidad (BiRefNet), solo para fotos dificiles.
                # Sin fallback: si no se puede descargar, el error se avisa.
                if self.session_max is None:
                    self.session_max = core.sesion_maxima(
                        lambda pct: self.cola.put(
                            ("estado", "Descargando modelo de maxima calidad "
                                       f"(una sola vez)... {pct}%")))
                    LOG.info("modelo maximo (birefnet) listo")
                session, fino = self.session_max, True
            else:
                if self.session is None:
                    # Modelo fino (mejor calado de pelo); si no se puede
                    # descargar, cae solo al modelo clasico de siempre.
                    self.session, self.fino = core.sesion_recorte(
                        self.preset,
                        lambda pct: self.cola.put(
                            ("estado", "Descargando mejora del recorte de pelo "
                                       f"(una sola vez)... {pct}%")))
                    LOG.info("modelo de recorte: " + ("fino (isnet)" if self.fino
                             else "CLASICO - no se pudo descargar el fino"))
                session, fino = self.session, self.fino
            # Auto-marcado de recortes DUDOSOS: solo en modo normal con el
            # modelo fino activo (en calidad maxima ya es lo mejor que hay, y
            # con el clasico no hay 2do modelo con que comparar). Corre u2net
            # ademas de isnet y marca donde discrepan (~1s extra por foto).
            detectar_dudosos = (not self.modo_maximo) and fino
            if detectar_dudosos and self.session_clasica is None:
                try:
                    self.session_clasica = core.new_session("u2net_human_seg")
                except Exception:
                    self.session_clasica = None
                    detectar_dudosos = False
            core.SALIDA.mkdir(parents=True, exist_ok=True)
            self.cola.put(("inicio", len(fotos)))
            ok = 0
            usados = {}  # codigo -> archivo, para detectar duplicados
            resumen = {"sin_cara": [], "sin_match": [], "ambiguo": [],
                       "duplicado": [], "pixelado": [], "dudoso": [],
                       "dudoso_rutas": [], "mejoradas": []}
            for i, ruta in enumerate(fotos, 1):
                if self.cancelado:
                    break
                try:
                    nombre_salida = None
                    revisar = False
                    if self.codigos:
                        # Si el operador YA eligio a mano esta foto en "Revisar
                        # pedido" (homonimo/typo dudoso), se respeta esa decision.
                        resuelto = self.resoluciones.get(ruta.name)
                        if resuelto:
                            codigo, estado = resuelto, "resuelto"
                        else:
                            codigo, estado = core.emparejar(ruta.stem, self.codigos)
                        if estado in ("exacto", "aproximado", "ya_codigo", "resuelto") and codigo:
                            if codigo in usados:
                                resumen["duplicado"].append(ruta.name)
                                revisar = True  # mismo codigo dos veces: dejar original
                            else:
                                usados[codigo] = ruta.name
                                nombre_salida = codigo
                        elif estado == "ambiguo":
                            resumen["ambiguo"].append(ruta.name)
                            revisar = True
                        else:
                            resumen["sin_match"].append(ruta.name)
                            revisar = True
                    sin_fondo = None
                    usar_session, usar_fino = session, fino
                    if detectar_dudosos:
                        sin_fondo, dudoso = core.evaluar_recorte(
                            ruta, session, self.session_clasica)
                        # Solo se auto-mejora si BiRefNet YA esta bajado (no
                        # dispara una descarga de ~900 MB sorpresa a mitad de lote).
                        auto_ok = (self.auto_mejora and
                                   (self.session_max is not None
                                    or core.modelo_maximo_descargado()))
                        if dudoso and auto_ok:
                            # AUTO-MEJORA: rehacer SOLA esta foto dudosa con
                            # BiRefNet (mejor matte) dentro del mismo lote.
                            try:
                                if self.session_max is None:
                                    self.cola.put(("estado",
                                        "Cargando el motor de calidad alta (una vez)..."))
                                    self.session_max = core.sesion_maxima()
                                    LOG.info("modelo maximo (birefnet) listo (auto)")
                                self.cola.put(("estado",
                                    f"Mejorando una foto dificil ({ruta.name})..."))
                                usar_session, usar_fino = self.session_max, True
                                sin_fondo = None  # birefnet calcula su propia mascara
                                resumen["mejoradas"].append(ruta.name)
                            except Exception:
                                resumen["dudoso"].append(ruta.name)
                                revisar = True
                        elif dudoso:
                            # auto apagada o BiRefNet no bajado -> marcar para
                            # "Foto dificil" manual.
                            resumen["dudoso"].append(ruta.name)
                            resumen["dudoso_rutas"].append(str(ruta))
                            revisar = True
                    destino, hubo_cara, pixelado = core.procesar_una(
                        ruta, self.preset, usar_session, nombre_salida,
                        fino=usar_fino, sin_fondo=sin_fondo)
                    if not hubo_cara:
                        resumen["sin_cara"].append(ruta.name)
                        revisar = True
                    if pixelado:
                        resumen["pixelado"].append(ruta.name)
                        revisar = True
                    ok += 1
                    self.cola.put(("una", i, str(destino), revisar))
                except Exception as e:
                    LOG.info(f"foto fallo {ruta.name}:\n" + traceback.format_exc())
                    self.cola.put(("error_una", i, str(e)))
            self.cola.put(("fin", ok, len(fotos), resumen))
        except Exception:
            self.cola.put(("fatal", traceback.format_exc()))

    def revisar_cola(self):
        try:
            while True:
                msg = self.cola.get_nowait()
                tag = msg[0]
                if tag == "inicio":
                    if self.modo_maximo:
                        self.estado.set(f"Procesando {msg[1]} foto(s) en CALIDAD "
                                        "MAXIMA (hasta ~1 min por foto)...")
                    else:
                        self.estado.set(f"Procesando {msg[1]} fotos...")
                elif tag == "estado":
                    self.estado.set(msg[1])
                elif tag == "una":
                    self.barra.config(value=msg[1])
                    self.resultados_listos.append(msg[2])
                    self.agregar_miniatura(msg[2], msg[3])
                elif tag == "error_una":
                    self.barra.config(value=msg[1])
                elif tag == "fin":
                    ok, total, resumen = msg[1], msg[2], msg[3]
                    cab = "Cancelado. " if self.cancelado else ""
                    self.estado.set(f"{cab}Listas: {ok} de {total}. Guardadas en: {core.SALIDA}")
                    # Registrar el lote (cliente, cantidad, fecha) para la recompra
                    renombradas = 0
                    if self.codigos:
                        renombradas = ok - len(resumen["sin_match"]) \
                            - len(resumen["ambiguo"]) - len(resumen["duplicado"])
                    cli = self.var_cliente.get()
                    core.registrar_lote("" if cli == SIN_CLIENTE else cli,
                                        ok, renombradas, core.SALIDA)
                    LOG.info(f"lote listo: {ok}/{total} ok | renombradas {renombradas} "
                             f"| mejoradas auto {len(resumen.get('mejoradas', []))}")
                    self.mostrar_resumen(ok, total, resumen)
                    self.terminar()
                    self.abrir_salida()
                    return
                elif tag == "rev_prog":
                    self.barra.config(value=msg[1])
                elif tag == "rev_fin":
                    rev, rutas = msg[1], msg[2]
                    self.resoluciones = {}
                    self.calidad_ok = set()
                    if rev.get("por_confirmar") or rev.get("por_calidad"):
                        self._resolver_confirmaciones(rev)
                    if rev.get("dni_alertas"):
                        self._avisar_dnis(rev["dni_alertas"])
                    self.rev_resultado = rev  # para el boton "Descargar reporte"
                    problemas = {f["nombre"] for f in rev["con_problema"]}
                    for r in rutas:
                        self.agregar_miniatura(r, Path(r).name in problemas)
                    texto = core.mensaje_para_cliente(rev)
                    self.txt_revision.delete("1.0", "end")
                    self.txt_revision.insert("1.0", texto)
                    self.btn_copiar.config(state="normal")
                    self.btn_reporte.config(state="normal")
                    LOG.info(f"revision: {rev['ok']}/{rev['total']} conformes | "
                             f"{len(rev['con_problema'])} con problema | "
                             f"{len(rev['sin_foto'])} sin foto")
                    pendientes = len(rev["con_problema"]) + len(rev["sin_foto"])
                    if pendientes == 0:
                        self.estado.set(f"Revision lista: TODO CONFORME "
                                        f"({rev['total']} fotos). Puede pasar a produccion.")
                    else:
                        self.estado.set(
                            f"Revision lista: {rev['ok']} de {rev['total']} conformes | "
                            f"{len(rev['con_problema'])} foto(s) con problema | "
                            f"{len(rev['sin_foto'])} persona(s) sin foto. "
                            "Mensaje listo para copiar.")
                    self.terminar()
                    return
                elif tag == "pdf_listo":
                    LOG.info("hoja de aprobacion generada: " + msg[1])
                    self.estado.set("Hoja de aprobacion lista: " + msg[1])
                    self.terminar()
                    try:
                        os.startfile(msg[1])
                    except Exception:
                        pass
                    return
                elif tag == "fin_firmas":
                    ok, total, fallas = msg[1], msg[2], msg[3]
                    LOG.info(f"firmas listas: {ok}/{total}")
                    cab = "Cancelado. " if self.cancelado else ""
                    self.estado.set(f"{cab}Firmas listas: {ok} de {total}. Guardadas en: {core.SALIDA}")
                    texto = (f"Se procesaron {ok} de {total} firma(s).\n"
                             "Salen en PNG con fondo transparente, recortadas al "
                             "trazo, en el color que elegiste.")
                    if fallas:
                        texto += "\n\nNo se pudieron procesar:\n- " + "\n- ".join(fallas[:6])
                        texto += ("\n\nConsejo: la firma debe verse oscura sobre "
                                  "papel claro, sin arrugas fuertes.")
                    messagebox.showinfo("Firmas", texto)
                    self.terminar()
                    self.abrir_salida()
                    return
                elif tag == "fatal":
                    self.estado.set("Hubo un error al procesar.")
                    self._avisar_error(msg[1])
                    self.terminar()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.revisar_cola)

    def terminar(self):
        self.procesando = False
        self._activar_botones(True)
        self._activar_cancelar(False)

    def _activar_cancelar(self, activo):
        self.btn_cancelar.config(state="normal" if activo else "disabled")

    def cancelar(self):
        # No corta en seco a media foto (eso podria dejar un archivo a medias):
        # marca la bandera y el worker se detiene al terminar la foto en curso.
        if not self.procesando:
            return
        self.cancelado = True
        self._activar_cancelar(False)
        self.estado.set("Cancelando... se detiene al terminar la foto actual.")

    # ---------- caja negra ----------
    def _error_interfaz(self, exc, val, tb):
        self._avisar_error("".join(traceback.format_exception(exc, val, tb)))

    def _avisar_error(self, texto_tecnico):
        # Registra el error, copia el diagnostico al portapapeles y avisa en
        # lenguaje simple. La persona solo tiene que PEGAR el reporte en el chat.
        LOG.info("ERROR:\n" + str(texto_tecnico).strip())
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(_diagnostico(texto_tecnico))
        except Exception:
            pass
        try:
            messagebox.showerror(
                "Ups, algo fallo",
                "El programa tuvo un problema con esta operacion.\n\n"
                "El reporte tecnico YA quedo copiado: abre el chat de soporte y "
                "pegalo con Ctrl+V para que lo revisen.\n\n"
                "Puedes seguir usando el programa con normalidad.")
        except Exception:
            pass

    # ---------- galeria ----------
    def limpiar_galeria(self):
        for w in self.galeria.winfo_children():
            w.destroy()
        self.thumbs.clear()
        self.col = 0
        self.fila = 0
        self.mostradas = 0

    def agregar_miniatura(self, ruta, revisar=False):
        if self.mostradas >= MAX_MINIATURAS:
            return
        try:
            img = Image.open(ruta)
            # Si es PNG transparente, mostrarlo sobre BLANCO en la vista previa
            # (asi se ve como saldra en un fotocheck claro, no con el fondo de la
            # celda asomandose, que confunde).
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                fondo = Image.new("RGB", img.size, (255, 255, 255))
                fondo.paste(img, mask=img.split()[-1])
                img = fondo
            else:
                img = img.convert("RGB")
            img.thumbnail((150, 150))
            tkimg = ImageTk.PhotoImage(img)
        except Exception:
            return
        self.thumbs.append(tkimg)
        # Marca en rojo las fotos a revisar (sin cara o nombre no emparejado).
        borde = COLOR_ALERTA if revisar else "#2b2b2b"
        celda = tk.Frame(self.galeria, bg=borde, highlightthickness=0)
        celda.grid(row=self.fila, column=self.col, padx=8, pady=8)
        tk.Label(celda, image=tkimg, bg=borde, bd=0,
                 padx=3, pady=3).pack()
        if revisar:
            tk.Label(celda, text="revisar", bg=COLOR_ALERTA, fg="#FFFFFF",
                     font=("Segoe UI", 8, "bold")).pack(fill="x")
        nombre = Path(ruta).stem
        tk.Label(celda, text=nombre[:18], bg="#2b2b2b", fg="#CFCFCF",
                 font=("Segoe UI", 8)).pack(fill="x")
        self.mostradas += 1
        self.col += 1
        if self.col >= 4:
            self.col = 0
            self.fila += 1

    def mostrar_resumen(self, ok, total, resumen):
        partes = [f"Se procesaron {ok} de {total} fotos."]
        if not self.fino:
            # Que el fallback NUNCA sea invisible: si no se pudo bajar el modelo
            # nuevo, el recorte de pelo sale como antes y hay que avisarlo.
            partes.append("\n\n(!) Se uso el recorte CLASICO de pelo: no se pudo "
                          "descargar la mejora (revisa el internet y vuelve a "
                          "procesar para intentarlo de nuevo).")
        # Solo cuentan como "a revisar" las categorias de problema (NO las
        # auto-mejoradas, que son buenas, ni dudoso_rutas, que duplica a dudoso).
        n_rev = sum(len(resumen[k]) for k in ("sin_cara", "sin_match", "ambiguo",
                                              "duplicado", "pixelado", "dudoso"))
        if resumen.get("mejoradas"):
            partes.append(f"\nSe mejoraron {len(resumen['mejoradas'])} foto(s) dificil(es) "
                          "solas, con el motor de calidad alta.")
        if self.codigos:
            renombradas = ok - len(resumen["sin_match"]) - len(resumen["ambiguo"]) - len(resumen["duplicado"])
            partes.append(f"Renombradas con su codigo: {renombradas}.")
        if n_rev == 0:
            partes.append("\nTodo salio bien, nada que revisar.")
        else:
            partes.append("\nRevisa estas (quedaron con su nombre original):")
            if resumen["sin_cara"]:
                partes.append(f"\n- Sin cara detectada ({len(resumen['sin_cara'])}): "
                              + ", ".join(resumen["sin_cara"][:8])
                              + (" ..." if len(resumen["sin_cara"]) > 8 else ""))
            if resumen["sin_match"]:
                partes.append(f"\n- No estan en el Excel ({len(resumen['sin_match'])}): "
                              + ", ".join(resumen["sin_match"][:8])
                              + (" ..." if len(resumen["sin_match"]) > 8 else ""))
            if resumen["ambiguo"]:
                partes.append(f"\n- Nombre repetido/ambiguo ({len(resumen['ambiguo'])}): "
                              + ", ".join(resumen["ambiguo"][:8])
                              + (" ..." if len(resumen["ambiguo"]) > 8 else ""))
            if resumen["duplicado"]:
                partes.append(f"\n- Codigo duplicado ({len(resumen['duplicado'])}): "
                              + ", ".join(resumen["duplicado"][:8])
                              + (" ..." if len(resumen["duplicado"]) > 8 else ""))
            if resumen["pixelado"]:
                partes.append(f"\n- Salieron borrosas/poca resolucion ({len(resumen['pixelado'])}): "
                              + ", ".join(resumen["pixelado"][:8])
                              + (" ..." if len(resumen["pixelado"]) > 8 else ""))
            if resumen.get("dudoso"):
                partes.append(f"\n- Recorte dudoso (ropa clara o pelo dificil): selecciona "
                              f"esas en 'Foto dificil' para rehacerlas mejor ({len(resumen['dudoso'])}): "
                              + ", ".join(resumen["dudoso"][:8])
                              + (" ..." if len(resumen["dudoso"]) > 8 else ""))
        messagebox.showinfo("Resumen", "".join(partes))


def _ruta_icono():
    import sys
    nombre = "icono.ico"
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(Path(sys._MEIPASS) / "recursos" / nombre)
    candidatos.append(core.BASE / "recursos" / nombre)
    for c in candidatos:
        if c.exists():
            return str(c)
    return None


def main():
    root = tk.Tk()
    ico = _ruta_icono()
    if ico:
        try:
            root.iconbitmap(ico)
        except Exception:
            pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

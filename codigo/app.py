import json
import os
import queue
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

import editar_fotos as core

EXT = core.EXTENSIONES
MAX_MINIATURAS = 24  # tope de miniaturas a mostrar (lotes grandes serian lentos)

COLOR_FONDO = "#383838"
COLOR_LILA = "#9987F7"
COLOR_LIMA = "#E7F849"
COLOR_TEXTO = "#FFFFFF"
COLOR_ALERTA = "#E74C3C"  # rojo para fotos a revisar

ULTIMO = core.BASE / "ultimo.json"  # recuerda el ultimo tamano usado


class App:
    def __init__(self, root):
        self.root = root
        try:
            self.preset = core.cargar_preset()
        except Exception:
            self.preset = None
        self.session = None
        self.thumbs = []          # referencias a las imagenes (evita que se borren)
        self.cola = queue.Queue()
        self.procesando = False
        self.codigos = []         # registros del Excel (codigo + nombre)
        self.ruta_excel = None

        root.title("Editor de Fotos Fotochecks - DISECOD")
        root.geometry("820x780")
        root.configure(bg=COLOR_FONDO)
        root.minsize(680, 660)

        cab = tk.Frame(root, bg=COLOR_FONDO)
        cab.pack(fill="x", padx=20, pady=(18, 8))
        tk.Label(cab, text="Editor de Fotos para Fotochecks",
                 bg=COLOR_FONDO, fg=COLOR_TEXTO,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(cab, text="Quita el fondo, ajusta el brillo y deja el tamano exacto. Todo automatico.",
                 bg=COLOR_FONDO, fg="#CFCFCF",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        botones = tk.Frame(root, bg=COLOR_FONDO)
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
        self.btn_abrir = tk.Button(botones, text="  Abrir resultados  ",
                                   command=self.abrir_salida,
                                   bg="#5a5a5a", fg=COLOR_TEXTO,
                                   activebackground="#6e6e6e",
                                   font=("Segoe UI", 11),
                                   relief="flat", cursor="hand2",
                                   padx=12, pady=10)
        self.btn_abrir.pack(side="right")

        # Tamano de salida editable (en pixeles), por si cada trabajo usa otra
        # medida. Recuerda el ultimo usado (tamano y formato) entre sesiones.
        ultimo = self._cargar_ultimo()
        ancho_def, alto_def = ultimo["ancho"], ultimo["alto"]
        medidas = tk.Frame(root, bg=COLOR_FONDO)
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

        # Formato de salida: PNG (mas calidad, pesa mas) o JPG (mas liviano).
        self.var_formato = tk.StringVar(value=ultimo["formato"])
        tk.Label(medidas, text="   Formato", bg=COLOR_FONDO, fg="#CFCFCF").pack(side="left", padx=(18, 3))
        for f in ("PNG", "JPG"):
            tk.Radiobutton(medidas, text=f, variable=self.var_formato, value=f,
                           bg=COLOR_FONDO, fg="#CFCFCF", selectcolor="#2b2b2b",
                           activebackground=COLOR_FONDO, activeforeground=COLOR_TEXTO).pack(side="left")

        # --- Encuadre y fondo ---
        op = tk.Frame(root, bg=COLOR_FONDO)
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

        # --- Correccion de color (automatica por foto) + anti-mancha de negros ---
        col = tk.Frame(root, bg=COLOR_FONDO)
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

        # --- Carpeta donde guardar (por defecto 'salida') ---
        self.salida_default = core.SALIDA
        self.carpeta_salida = None
        dest = tk.Frame(root, bg=COLOR_FONDO)
        dest.pack(fill="x", padx=20, pady=(2, 4))
        self.btn_destino = tk.Button(dest, text="  Guardar en...  ",
                                     command=self.elegir_destino, bg="#5a5a5a",
                                     fg=COLOR_TEXTO, activebackground="#6e6e6e",
                                     font=("Segoe UI", 10), relief="flat",
                                     cursor="hand2", padx=10, pady=6)
        self.btn_destino.pack(side="left")
        self.var_destino = tk.StringVar(value="Se guarda en la carpeta 'salida'. Puedes elegir otra (ej. la del cliente).")
        tk.Label(dest, textvariable=self.var_destino, bg=COLOR_FONDO, fg="#CFCFCF",
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))

        # Excel de codigos (opcional): renombra cada foto al codigo del empleado
        # para que CardPresso la enlace sola.
        excel_row = tk.Frame(root, bg=COLOR_FONDO)
        excel_row.pack(fill="x", padx=20, pady=(2, 4))
        self.btn_excel = tk.Button(excel_row, text="  Elegir Excel de codigos  ",
                                   command=self.elegir_excel,
                                   bg="#5a5a5a", fg=COLOR_TEXTO,
                                   activebackground="#6e6e6e",
                                   font=("Segoe UI", 10),
                                   relief="flat", cursor="hand2",
                                   padx=10, pady=6)
        self.btn_excel.pack(side="left")
        self.var_excel = tk.StringVar(
            value="Opcional: las fotos salen con su nombre original.")
        tk.Label(excel_row, textvariable=self.var_excel, bg=COLOR_FONDO,
                 fg="#CFCFCF", font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))

        self.estado = tk.StringVar(value="Elige las fotos para empezar.")
        tk.Label(root, textvariable=self.estado, bg=COLOR_FONDO, fg=COLOR_LIMA,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=20)

        self.barra = ttk.Progressbar(root, mode="determinate")
        self.barra.pack(fill="x", padx=20, pady=(4, 10))

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

    def elegir_destino(self):
        if self.procesando:
            return
        d = filedialog.askdirectory(title="Elegir carpeta donde guardar las fotos")
        if d:
            self.carpeta_salida = Path(d)
            self.var_destino.set("Se guarda en: " + d)

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
    def elegir_fotos(self):
        if self.procesando:
            return
        rutas = filedialog.askopenfilenames(
            title="Elegir fotos",
            filetypes=[("Imagenes", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"),
                       ("Todos los archivos", "*.*")])
        if rutas:
            self.iniciar([Path(r) for r in rutas])

    def elegir_carpeta(self):
        if self.procesando:
            return
        d = filedialog.askdirectory(title="Elegir carpeta con fotos")
        if d:
            fotos = [q for q in sorted(Path(d).iterdir()) if q.suffix.lower() in EXT]
            self.iniciar(fotos)

    def abrir_salida(self):
        try:
            core.SALIDA.mkdir(parents=True, exist_ok=True)
            os.startfile(core.SALIDA)
        except Exception:
            pass

    # ---------- procesar ----------
    def iniciar(self, fotos):
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
        # Carpeta destino (la elegida o la de por defecto)
        core.SALIDA = self.carpeta_salida or self.salida_default
        self._guardar_ultimo(medidas[0], medidas[1], self.var_formato.get())
        self.limpiar_galeria()
        self.procesando = True
        self.btn_fotos.config(state="disabled")
        self.btn_carpeta.config(state="disabled")
        self.btn_excel.config(state="disabled")
        self.btn_destino.config(state="disabled")
        self.barra.config(maximum=len(fotos), value=0)
        self.estado.set("Preparando modelo de IA...")
        threading.Thread(target=self.worker, args=(fotos,), daemon=True).start()
        self.root.after(100, self.revisar_cola)

    def worker(self, fotos):
        try:
            if self.preset is None:
                self.preset = core.cargar_preset()
            if self.session is None:
                self.session = core.new_session(self.preset["modelo_recorte"])
            core.SALIDA.mkdir(parents=True, exist_ok=True)
            self.cola.put(("inicio", len(fotos)))
            ok = 0
            usados = {}  # codigo -> archivo, para detectar duplicados
            resumen = {"sin_cara": [], "sin_match": [], "ambiguo": [],
                       "duplicado": [], "pixelado": []}
            for i, ruta in enumerate(fotos, 1):
                try:
                    nombre_salida = None
                    revisar = False
                    if self.codigos:
                        codigo, estado = core.emparejar(ruta.stem, self.codigos)
                        if estado in ("exacto", "aproximado", "ya_codigo") and codigo:
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
                    destino, hubo_cara, pixelado = core.procesar_una(
                        ruta, self.preset, self.session, nombre_salida)
                    if not hubo_cara:
                        resumen["sin_cara"].append(ruta.name)
                        revisar = True
                    if pixelado:
                        resumen["pixelado"].append(ruta.name)
                        revisar = True
                    ok += 1
                    self.cola.put(("una", i, str(destino), revisar))
                except Exception as e:
                    self.cola.put(("error_una", i, str(e)))
            self.cola.put(("fin", ok, len(fotos), resumen))
        except Exception as e:
            self.cola.put(("fatal", str(e)))

    def revisar_cola(self):
        try:
            while True:
                msg = self.cola.get_nowait()
                tag = msg[0]
                if tag == "inicio":
                    self.estado.set(f"Procesando {msg[1]} fotos...")
                elif tag == "una":
                    self.barra.config(value=msg[1])
                    self.agregar_miniatura(msg[2], msg[3])
                elif tag == "error_una":
                    self.barra.config(value=msg[1])
                elif tag == "fin":
                    ok, total, resumen = msg[1], msg[2], msg[3]
                    self.estado.set(f"Listas: {ok} de {total}. Resultados en la carpeta 'salida'.")
                    self.mostrar_resumen(ok, total, resumen)
                    self.terminar()
                    self.abrir_salida()
                    return
                elif tag == "fatal":
                    self.estado.set("Hubo un error al procesar.")
                    messagebox.showerror("Error", str(msg[1]))
                    self.terminar()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.revisar_cola)

    def terminar(self):
        self.procesando = False
        self.btn_fotos.config(state="normal")
        self.btn_carpeta.config(state="normal")
        self.btn_excel.config(state="normal")
        self.btn_destino.config(state="normal")

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
        n_rev = sum(len(v) for v in resumen.values())
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

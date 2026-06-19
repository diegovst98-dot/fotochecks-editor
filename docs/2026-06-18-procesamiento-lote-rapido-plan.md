# Procesamiento lote rápido + mejorar-las-que-elijas — Plan (Fase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans para
> implementar tarea por tarea. Pasos con checkbox (`- [ ]`).

**Goal:** El lote corre solo isnet (rápido); al terminar, un diálogo de miniaturas
con checkbox deja rehacer SOLO las que el operador elija con BiRefNet, en sitio.

**Architecture:** Cambios SOLO en `codigo/app.py` (flujo/UI del worker). Se elimina
el BiRefNet automático inline; el detector de dudosas se mantiene (marca, no rehace);
la mejora pasa a un diálogo post-lote que reusa el camino `iniciar(maxima=True)` (que
ya sobreescribe en la misma carpeta). No toca `procesar_una`/`retoque` → las doradas
NO cambian.

**Tech Stack:** Python/Tkinter. Runner propio (`tests/correr_tests.py`, no pytest).
GUI no testeable por unidad → el test es el humo de interfaz [6/6] + doradas verdes.

**Flujo de git (deliberado):** repo de distribución; `push` = auto-update a Mirza.
Sin commit por tarea; al final, con OK de Diego, `publicar.py` (commit+push). NO se
reconstruye el .exe (solo código).

---

## File Structure
- **Modify** `codigo/app.py`:
  - `worker()` — quitar auto-mejora inline; marcar dudosas; juntar `dudoso_pares`.
  - quitar checkbox/var `var_auto_mejora` y `self.auto_mejora` en `iniciar`.
  - `revisar_cola` rama `fin` — ofrecer el diálogo post-lote.
  - nuevo método `_ofrecer_mejora_dificiles(pares)`.
  - `mostrar_resumen` — ajustar el texto de "dudoso".
- **Modify** `tests/correr_tests.py` — humo [6/6]: check del nuevo método.

---

### Task 1: Worker — marcar dudosas (sin BiRefNet inline) + juntar pares entrada/salida

**Files:** Modify `codigo/app.py` (`worker`, ~1373-1446)

- [ ] **Step 1: Cambiar la init del `resumen`** (la línea con `"dudoso_rutas": []`)

Buscar:
```python
            resumen = {"sin_cara": [], "sin_match": [], "ambiguo": [],
                       "duplicado": [], "pixelado": [], "dudoso": [],
                       "dudoso_rutas": [], "mejoradas": []}
```
Reemplazar por:
```python
            resumen = {"sin_cara": [], "sin_match": [], "ambiguo": [],
                       "duplicado": [], "pixelado": [], "dudoso": [],
                       "dudoso_pares": [], "mejoradas": []}
```

- [ ] **Step 2: Reemplazar el bloque de detección/auto-mejora**

Buscar el bloque completo (dentro del `for`, ~1403-1435):
```python
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
```
Reemplazar por:
```python
                    sin_fondo = None
                    era_dudoso = False
                    if detectar_dudosos:
                        # Solo MARCA las dudosas (recorte dudoso = ropa clara o pelo
                        # dificil); ya NO se rehacen solas con BiRefNet inline (era
                        # lento y casi todas salen bien con isnet+apretado). Se
                        # reusa el matte de isnet (sin_fondo) para no correrlo 2 veces.
                        sin_fondo, dudoso = core.evaluar_recorte(
                            ruta, session, self.session_clasica)
                        if dudoso:
                            resumen["dudoso"].append(ruta.name)
                            era_dudoso = True
                            revisar = True
                    destino, hubo_cara, pixelado = core.procesar_una(
                        ruta, self.preset, session, nombre_salida,
                        fino=fino, sin_fondo=sin_fondo)
                    if era_dudoso:
                        resumen["dudoso_pares"].append((str(ruta), str(destino)))
```

- [ ] **Step 3: Verificar que compila**

Run: `cd C:\Users\Diego\fotochecks-editor && python -c "import sys; sys.path.insert(0,'codigo'); import app; print('app OK')"`
Expected: `app OK` (sin errores; `self.auto_mejora` ya no se usa en worker).

---

### Task 2: Quitar el checkbox "Mejorar las difíciles automáticamente" y su var

**Files:** Modify `codigo/app.py` (~287-297 y ~1248)

- [ ] **Step 1: Quitar el checkbox + comentario** (líneas ~287-297)

Buscar:
```python
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
```
Reemplazar por:
```python
        # Las fotos con recorte DUDOSO (pelo dificil / ropa clara) se MARCAN y, al
        # terminar el lote, un dialogo deja rehacer SOLO las que el operador elija
        # con el motor de calidad alta (BiRefNet). Ya no se rehacen solas inline
        # (era lento y casi todas salen bien con isnet+apretado).
```

- [ ] **Step 2: Quitar `self.auto_mejora` en `iniciar`** (línea ~1246-1248)

Buscar:
```python
        self.modo_maximo = maxima
        # La auto-mejora de las dudosas solo aplica en modo normal (en "Foto
        # dificil" el lote YA va con el motor de maxima calidad).
        self.auto_mejora = self.var_auto_mejora.get() and not maxima
```
Reemplazar por:
```python
        self.modo_maximo = maxima
```

- [ ] **Step 3: Verificar que compila**

Run: `cd C:\Users\Diego\fotochecks-editor && python -c "import sys; sys.path.insert(0,'codigo'); import app; print('app OK')"`
Expected: `app OK`.

---

### Task 3: Diálogo post-lote `_ofrecer_mejora_dificiles` + enganche en `fin`

**Files:** Modify `codigo/app.py` (nuevo método tras `_resolver_confirmaciones` ~1179; y rama `fin` ~1487-1490)

- [ ] **Step 1: Agregar el método** (insertar justo ANTES de `def _avisar_dnis(self, alertas):`, línea ~1180)

```python
    def _ofrecer_mejora_dificiles(self, pares):
        # pares = [(ruta_entrada, ruta_salida)] de las marcadas como recorte dudoso.
        # Muestra cada SALIDA (como quedo) con checkbox; las marcadas se rehacen con
        # BiRefNet (calidad alta) sobreescribiendo en la misma carpeta. Devuelve
        # True si lanzo un reproceso.
        if not pares:
            return False
        win = tk.Toplevel(self.root)
        win.title("Mejorar las fotos dificiles")
        win.configure(bg=COLOR_FONDO)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text=(f"{len(pares)} foto(s) salieron a revisar (recorte "
                            "dudoso). Marca las que quieras rehacer con calidad alta "
                            "(mas lento). Las que no marques quedan como estan."),
                 bg=COLOR_FONDO, fg=COLOR_TEXTO, font=("Segoe UI", 11),
                 wraplength=560, justify="left").pack(anchor="w", padx=16, pady=(14, 8))
        cont = tk.Frame(win, bg=COLOR_FONDO)
        cont.pack(fill="both", expand=True, padx=8)
        canvas = tk.Canvas(cont, bg=COLOR_FONDO, highlightthickness=0,
                           height=380, width=600)
        sb = ttk.Scrollbar(cont, orient="vertical", command=canvas.yview)
        marco = tk.Frame(canvas, bg=COLOR_FONDO)
        marco.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=marco, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._dlg_thumbs = []
        checks = []  # (ruta_entrada, BooleanVar)
        for entrada, salida in pares:
            blq = tk.Frame(marco, bg="#2b2b2b", highlightthickness=1,
                           highlightbackground="#4a4a4a")
            blq.pack(fill="x", expand=True, padx=6, pady=5)
            try:
                im = Image.open(salida)
                if _ImageOps is not None:
                    im = _ImageOps.exif_transpose(im)
                im = im.convert("RGB")
                im.thumbnail((84, 104))
                ph = ImageTk.PhotoImage(im)
                self._dlg_thumbs.append(ph)
                tk.Label(blq, image=ph, bg="#2b2b2b").pack(side="left", padx=8, pady=8)
            except Exception:
                pass
            bv = tk.BooleanVar(value=False)
            tk.Checkbutton(blq, text=Path(entrada).name, variable=bv, bg="#2b2b2b",
                           fg=COLOR_TEXTO, selectcolor="#1d1d1d",
                           activebackground="#2b2b2b", activeforeground=COLOR_TEXTO,
                           font=("Segoe UI", 10)).pack(side="left", padx=8)
            checks.append((entrada, bv))
        self._mejora_lanzada = False

        def mejorar():
            elegidas = [Path(e) for e, v in checks if v.get()]
            win.destroy()
            if elegidas:
                self._mejora_lanzada = True
                self.iniciar(elegidas, maxima=True)

        barra = tk.Frame(win, bg=COLOR_FONDO)
        barra.pack(fill="x", padx=16, pady=12)
        tk.Button(barra, text="  Mejorar las marcadas  ", command=mejorar,
                  bg=COLOR_LIMA, fg="#1d1d1d", activebackground="#eefb7a",
                  font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
                  padx=14, pady=6).pack(side="right")
        tk.Button(barra, text="  Dejar asi  ", command=win.destroy, bg="#5a5a5a",
                  fg=COLOR_TEXTO, activebackground="#6e6e6e",
                  font=("Segoe UI", 10), relief="flat", cursor="hand2",
                  padx=12, pady=6).pack(side="right", padx=(0, 8))
        win.update_idletasks()
        win.geometry(f"+{self.root.winfo_rootx() + 60}+{self.root.winfo_rooty() + 60}")
        self.root.wait_window(win)
        return self._mejora_lanzada
```

- [ ] **Step 2: Enganchar en la rama `fin`** de `revisar_cola` (~1487-1490)

Buscar:
```python
                    self.mostrar_resumen(ok, total, resumen)
                    self.terminar()
                    self.abrir_salida()
                    return
```
Reemplazar por:
```python
                    self.mostrar_resumen(ok, total, resumen)
                    self.terminar()
                    relanzo = False
                    if (not self.modo_maximo and not self.cancelado
                            and resumen.get("dudoso_pares")):
                        relanzo = self._ofrecer_mejora_dificiles(
                            resumen["dudoso_pares"])
                    if not relanzo:
                        self.abrir_salida()
                    return
```

- [ ] **Step 3: Verificar que compila**

Run: `cd C:\Users\Diego\fotochecks-editor && python -c "import sys; sys.path.insert(0,'codigo'); import app; print('app OK')"`
Expected: `app OK`.

---

### Task 4: Ajustar el texto del resumen (apunta al diálogo, no a "Foto difícil")

**Files:** Modify `codigo/app.py` (`mostrar_resumen`, ~1711-1715)

- [ ] **Step 1: Cambiar el texto del bloque "dudoso"**

Buscar:
```python
            if resumen.get("dudoso"):
                partes.append(f"\n- Recorte dudoso (ropa clara o pelo dificil): selecciona "
                              f"esas en 'Foto dificil' para rehacerlas mejor ({len(resumen['dudoso'])}): "
                              + ", ".join(resumen["dudoso"][:8])
                              + (" ..." if len(resumen["dudoso"]) > 8 else ""))
```
Reemplazar por:
```python
            if resumen.get("dudoso"):
                partes.append(f"\n- Recorte dudoso (ropa clara o pelo dificil) "
                              f"({len(resumen['dudoso'])}): te pregunto cuales rehacer "
                              "con calidad alta en la ventana siguiente. "
                              + ", ".join(resumen["dudoso"][:8])
                              + (" ..." if len(resumen["dudoso"]) > 8 else ""))
```

- [ ] **Step 2: Verificar que compila**

Run: `cd C:\Users\Diego\fotochecks-editor && python -c "import sys; sys.path.insert(0,'codigo'); import app; print('app OK')"`
Expected: `app OK`.

---

### Task 5: Humo de interfaz en el candado + candado verde

**Files:** Modify `tests/correr_tests.py` (sección [6/6], ~415-421)

- [ ] **Step 1: Agregar el check del nuevo diálogo**

Buscar:
```python
        check("boton Foto dificil existe", hasattr(a, "btn_dificil"))
```
Reemplazar por:
```python
        check("boton Foto dificil existe", hasattr(a, "btn_dificil"))
        check("dialogo mejorar dificiles (post-lote)",
              hasattr(a, "_ofrecer_mejora_dificiles")
              and not hasattr(a, "var_auto_mejora"))
```

- [ ] **Step 2: Candado completo verde (las doradas NO deben cambiar)**

Run: `cd C:\Users\Diego\fotochecks-editor && python tests\correr_tests.py`
Expected: `RESULTADO: TODO OK`. En particular: las 20 doradas de foto en OK (NO cambiaron, porque no se tocó `procesar_una`/`retoque`), `test_alfa` OK, y el nuevo check de interfaz en OK. Si una dorada fallara, PARAR (algo se tocó que no debía).

---

### Task 6: Publicar (CHECKPOINT — OK explícito de Diego)

- [ ] **Step 1: Mostrar a Diego el candado verde y esperar su "publica".** Sin OK, no seguir.
- [ ] **Step 2:** Run: `cd C:\Users\Diego\fotochecks-editor && python publicar.py` → candado verde + sube versión + commit + push.
- [ ] **Step 3:** Avisar a Mirza: cerrar/reabrir el editor (baja la versión sola) y correr un lote para ver el nuevo flujo (rápido + ventana de "mejorar las difíciles").

---

## Self-Review (hecho)
- **Cobertura del spec:** worker solo marca (T1) ✓; quita checkbox/var auto-mejora
  (T2) ✓; diálogo post-lote con miniaturas+checkbox → BiRefNet en sitio reusando
  `iniciar(maxima=True)` (T3) ✓; detector se queda ✓; resumen apunta al diálogo (T4)
  ✓; doradas no cambian + humo (T5) ✓; publicar con OK (T6) ✓.
- **Sin placeholders:** todo el código y comandos están completos.
- **Consistencia:** `dudoso_pares` (init T1 → append T1 → consumo T3); el diálogo usa
  `iniciar(maxima=True)` (existente) que escribe en `core.SALIDA` con el mismo
  `nombre_salida` → sobreescribe en sitio. `_ImageOps`, `ImageTk`, `COLOR_LIMA`,
  `COLOR_FONDO`, `COLOR_TEXTO` ya se usan en `_resolver_confirmaciones` (existen).
- **Riesgo:** en modo `maxima` el worker no corre el detector (`detectar_dudosos`
  False) → el reproceso no re-abre el diálogo (no hay loop). Sin imports nuevos.

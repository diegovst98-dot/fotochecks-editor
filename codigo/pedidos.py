# Pedidos: revision previa de insumos (semaforo), mensaje al cliente, hoja de
# aprobacion en PDF y registro de lotes. Es la cara "comercial" del editor.
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
try:
    from PIL import ImageOps          # para corregir la rotacion EXIF (fotos de celular)
except Exception:
    ImageOps = None

import encuadre
import excel_codigos

# HEIC (fotos de iPhone): si pillow-heif esta disponible (exe nuevo) se registra
# para que Image.open abra .heic/.heif. Import DINAMICO a proposito: en un exe
# viejo que no lo trae NO rompe (cae a un aviso claro) y el candado no lo exige.
try:
    import importlib
    _ph = importlib.import_module("pillow_heif")
    _ph.register_heif_opener()
    _HEIC_OK = True
except Exception:
    _HEIC_OK = False


# ---------- revision previa del pedido (semaforo de insumos) ----------
# Revisa fotos + Excel ANTES de producir, para detectar de una sola vez todo lo
# que falta o esta mal y pedirselo al cliente en UN solo mensaje (en vez de
# descubrir los problemas a mitad de la produccion, uno por uno).

def _nitidez(img):
    # Varianza del laplaciano sobre la foto a ancho fijo: numero bajo = borrosa.
    g = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if g.shape[1] > 800:
        esc = 800.0 / g.shape[1]
        g = cv2.resize(g, (800, max(1, int(g.shape[0] * esc))))
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _es_problema_calidad(p):
    # Problemas de CALIDAD de imagen que el operador puede "perdonar" (la foto va
    # igual): borrosa, baja resolucion o cara no detectada. NO incluye "dañado"
    # (ese archivo no se puede abrir/procesar).
    return "borrosa" in p or "resolucion" in p or "no se distingue" in p


def revisar_fotos(fotos, codigos=None, progreso=None):
    # Devuelve un resumen del estado del pedido SIN procesar nada.
    # Ademas de los problemas de calidad, clasifica el cruce con el Excel:
    # los casos 'sugerencia' (un parecido, confirmar) y 'ambiguo' (varios, elegir)
    # se juntan en rev["por_confirmar"] con sus candidatos, para resolverlos a mano
    # en la UI ANTES de armar el mensaje al cliente (asi un typo no se pide de mas).
    rev = {"total": len(fotos), "fotos": [], "sin_foto": [], "duplicados": [],
           "por_confirmar": [], "con_excel": bool(codigos),
           "dni_alertas": excel_codigos.dni_sospechosos(codigos) if codigos else []}
    usados = {}   # codigo -> primer archivo que lo uso
    emparejados = set()
    for i, ruta in enumerate(fotos, 1):
        problemas = []
        estado = None
        candidatos = []
        try:
            img = Image.open(ruta)
            img.load()
            if ImageOps is not None:  # endereza fotos de celular (orientacion EXIF)
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
        except Exception:
            ext = ruta.suffix.lower()
            if ext in (".heic", ".heif") and not _HEIC_OK:
                prob = "es foto de iPhone (HEIC); pidela exportada como JPG"
            else:
                prob = "el archivo esta dañado o no es una foto"
            rev["fotos"].append({"nombre": ruta.name, "estado": "error",
                                 "candidatos": [], "problemas": [prob]})
            if progreso:
                progreso(i)
            continue
        if min(img.size) < 400:
            problemas.append("resolucion muy baja (saldra pixelada)")
        elif _nitidez(img) < 45.0:
            problemas.append("se ve borrosa")
        if encuadre.detectar_cara(img.convert("RGB")) is None:
            problemas.append("no se distingue una cara (¿foto de otra cosa?)")
        if codigos:
            d = excel_codigos.emparejar_detalle(ruta.stem, codigos)
            estado, candidatos, codigo = d["estado"], d["candidatos"], d["codigo"]
            if estado in ("exacto", "aproximado", "ya_codigo") and codigo:
                if codigo in usados:
                    rev["duplicados"].append(
                        f"{ruta.name} y {usados[codigo]} parecen ser de la misma persona (codigo {codigo})")
                else:
                    usados[codigo] = ruta.name
                    emparejados.add(codigo)
            elif estado == "sugerencia" and candidatos:
                problemas.append(f"¿es {candidatos[0]['nombre']}? (confirmar)")
                rev["por_confirmar"].append(
                    {"nombre": ruta.name, "estado": estado, "candidatos": candidatos})
            elif estado == "ambiguo":
                problemas.append("el nombre coincide con VARIAS personas del Excel")
                rev["por_confirmar"].append(
                    {"nombre": ruta.name, "estado": estado, "candidatos": candidatos})
            else:
                problemas.append("no encontramos este nombre en el Excel")
        rev["fotos"].append({"nombre": ruta.name, "estado": estado,
                             "candidatos": candidatos, "problemas": problemas})
        if progreso:
            progreso(i)
    if codigos:
        for r in codigos:
            if r["codigo"] not in emparejados:
                rev["sin_foto"].append(f'{r["codigo"]} - {r["nombre"]}')
    rev["por_calidad"] = [
        {"nombre": f["nombre"],
         "problemas": [p for p in f["problemas"] if _es_problema_calidad(p)]}
        for f in rev["fotos"]
        if any(_es_problema_calidad(p) for p in f["problemas"])]
    rev["con_problema"] = [f for f in rev["fotos"] if f["problemas"]]
    rev["ok"] = rev["total"] - len(rev["con_problema"])
    return rev


def aplicar_resoluciones(rev, resoluciones, calidad_ok=None):
    # Aplica las decisiones del operador (dialogo de la UI) sobre un 'rev' ya
    # calculado:
    #   resoluciones = {nombre_archivo: codigo}  -> homonimo/typo elegido a mano
    #   calidad_ok   = {nombre_archivo, ...}      -> "esta foto va igual" (perdona
    #                                                el aviso de borrosa/resolucion)
    # Los casos resueltos salen de los problemas (y de 'sin_foto') para que el
    # mensaje al cliente quede limpio.
    resoluciones = resoluciones or {}
    calidad_ok = set(calidad_ok or [])
    if not resoluciones and not calidad_ok:
        return rev
    resueltos_cod = set()
    for f in rev["fotos"]:
        cod = resoluciones.get(f["nombre"])
        if cod:
            f["problemas"] = [p for p in f["problemas"]
                              if not (p.startswith("¿es ")
                                      or "VARIAS personas" in p
                                      or "no encontramos" in p)]
            f["estado"] = "resuelto"
            f["codigo_resuelto"] = str(cod)
            resueltos_cod.add(str(cod))
        if f["nombre"] in calidad_ok:
            f["problemas"] = [p for p in f["problemas"] if not _es_problema_calidad(p)]
    rev["sin_foto"] = [s for s in rev["sin_foto"]
                       if s.split(" - ", 1)[0].strip() not in resueltos_cod]
    rev["por_confirmar"] = [c for c in rev["por_confirmar"]
                            if not resoluciones.get(c["nombre"])]
    rev["por_calidad"] = [c for c in rev.get("por_calidad", [])
                          if c["nombre"] not in calidad_ok]
    rev["con_problema"] = [f for f in rev["fotos"] if f["problemas"]]
    rev["ok"] = rev["total"] - len(rev["con_problema"])
    return rev


def reporte_csv(rev, destino):
    # Escribe un CSV con el detalle de la revision: una fila por foto + las
    # personas sin foto + los DNI a revisar. Sirve de respaldo/auditoria del
    # pedido (se abre en Excel). Usa solo stdlib (csv), va dentro del .exe.
    import csv
    destino = Path(destino)
    with open(destino, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["REVISION DE PEDIDO"])
        w.writerow(["Total fotos", rev.get("total", 0),
                    "Conformes", rev.get("ok", 0)])
        w.writerow([])
        w.writerow(["Archivo", "Estado", "Problemas", "Codigo asignado"])
        for f in rev.get("fotos", []):
            w.writerow([f.get("nombre", ""), f.get("estado") or "",
                        " / ".join(f.get("problemas", [])),
                        f.get("codigo_resuelto", "")])
        if rev.get("sin_foto"):
            w.writerow([])
            w.writerow(["PERSONAS SIN FOTO (estan en la lista del cliente)"])
            for s in rev["sin_foto"]:
                w.writerow([s])
        if rev.get("dni_alertas"):
            w.writerow([])
            w.writerow(["DNI A REVISAR", "Nombre", "Motivo"])
            for cod, nom, mot in rev["dni_alertas"]:
                w.writerow([cod, nom, mot])
    return destino


# ---------- Renombrar para CardPresso (solo renombrar, sin editar la imagen) ----------
# Toma fotos ya listas + el Excel del cliente y saca COPIAS nombradas <DNI>.<ext>
# para que CardPresso las enlace. Reusa el mismo matching tolerante del editor.

_ESTADOS_OK = ("exacto", "aproximado", "ya_codigo", "resuelto")


def _ext_cardpresso(ext):
    e = ext.lower()
    if e in (".jpeg", ".jpg"):
        return ".jpg"
    if e == ".png":
        return ".png"
    return e


def plan_cardpresso(fotos, codigos, resoluciones=None):
    # Arma el plan de renombrado SIN tocar archivos (matching solo por nombre).
    # Devuelve {plan, por_confirmar, duplicados}. 'resoluciones' = {nombre: codigo}
    # con lo elegido a mano (homonimos/typos dudosos).
    resoluciones = resoluciones or {}
    plan = []
    por_confirmar = []
    usados = {}
    for ruta in fotos:
        nombre = ruta.name
        elegido = resoluciones.get(nombre)
        if elegido:
            codigo, estado, cands = str(elegido), "resuelto", []
        else:
            d = excel_codigos.emparejar_detalle(ruta.stem, codigos)
            codigo, estado, cands = d["codigo"], d["estado"], d["candidatos"]
            if estado in ("sugerencia", "ambiguo"):
                por_confirmar.append({"nombre": nombre, "estado": estado, "candidatos": cands})
        plan.append({"nombre": nombre, "ruta": str(ruta), "codigo": codigo,
                     "estado": estado, "candidatos": cands})
        if codigo and estado in _ESTADOS_OK:
            usados.setdefault(str(codigo), []).append(nombre)
    duplicados = {k: v for k, v in usados.items() if len(v) > 1}
    return {"plan": plan, "por_confirmar": por_confirmar, "duplicados": duplicados}


def aplicar_cardpresso(plan, salida, formato_unico=False, progreso=None):
    # Copia las fotos que cruzaron a 'salida' como <DNI>.<ext> (originales intactas)
    # y escribe _verificacion.csv. formato_unico=True las convierte todas a .jpg.
    # Devuelve {copiadas, sin_match, duplicadas, carpeta}.
    import csv
    import shutil
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    filas = []
    sin_match = []
    errores = []
    vistos = {}
    duplicadas = []
    copiadas = 0
    for i, p in enumerate(plan, 1):
        cod = str(p["codigo"]) if p["codigo"] else ""
        if not cod or p["estado"] not in _ESTADOS_OK:
            sin_match.append(p["nombre"])
        elif cod in vistos:
            duplicadas.append(f'{p["nombre"]} (DNI {cod} ya usado por {vistos[cod]})')
        else:
            try:
                ext = ".jpg" if formato_unico else _ext_cardpresso(Path(p["ruta"]).suffix)
                destino = salida / f"{cod}{ext}"
                if formato_unico:
                    im = Image.open(p["ruta"])
                    if ImageOps is not None:
                        im = ImageOps.exif_transpose(im)
                    im.convert("RGB").save(destino, "JPEG", quality=95)
                else:
                    shutil.copy2(p["ruta"], destino)
                vistos[cod] = p["nombre"]
                filas.append([cod, p["nombre"], destino.name, p["estado"]])
                copiadas += 1
            except Exception:
                # una foto dañada NO tumba el lote: se marca y se sigue.
                errores.append(p["nombre"])
        if progreso:
            progreso(i)
    with open(salida / "_verificacion.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["DNI", "Archivo_original", "Archivo_nuevo", "Metodo"])
        for f in filas:
            w.writerow(f)
        if sin_match:
            w.writerow([])
            w.writerow(["SIN CRUZAR con el Excel (revisar a mano)"])
            for n in sin_match:
                w.writerow([n])
        if duplicadas:
            w.writerow([])
            w.writerow(["DNI REPETIDO (no copiadas)"])
            for n in duplicadas:
                w.writerow([n])
        if errores:
            w.writerow([])
            w.writerow(["NO SE PUDIERON ABRIR (dañadas)"])
            for n in errores:
                w.writerow([n])
    return {"copiadas": copiadas, "sin_match": sin_match, "duplicadas": duplicadas,
            "errores": errores, "carpeta": str(salida)}


def mensaje_para_cliente(rev, cliente=""):
    # Texto listo para copiar y mandar por WhatsApp al cliente. Si se pasa
    # 'cliente', el saludo lo nombra ("Hola, equipo de X 👋").
    saludo = f"Hola, equipo de {cliente.strip()} 👋" if cliente.strip() else "Hola 👋"
    lineas = []
    if rev["sin_foto"]:
        lineas.append("*FALTAN LAS FOTOS de estas personas (estan en tu lista):*")
        lineas += [f"  - {p}" for p in rev["sin_foto"]]
        lineas.append("")
    borrosas = [f for f in rev["con_problema"]
                if any("borrosa" in p or "resolucion" in p or "dañado" in p
                       or "HEIC" in p for p in f["problemas"])]
    if borrosas:
        lineas.append("*REENVIAR estas fotos por favor (salieron con problemas):*")
        lineas += [f'  - {f["nombre"]}: {", ".join(f["problemas"])}' for f in borrosas]
        lineas.append("")
    sin_lista = [f for f in rev["con_problema"]
                 if any("Excel" in p for p in f["problemas"])]
    if sin_lista:
        lineas.append("*Estas fotos no figuran en tu lista (confirmanos el nombre o agregalos):*")
        lineas += [f'  - {f["nombre"]}' for f in sin_lista]
        lineas.append("")
    if rev["duplicados"]:
        lineas.append("*Fotos repetidas (confirmanos cual usamos):*")
        lineas += [f"  - {d}" for d in rev["duplicados"]]
        lineas.append("")
    if not lineas:
        extra = " y la lista de personal" if rev["con_excel"] else ""
        return (f"{saludo} ¡Todo conforme! ✅ Revisamos las {rev['total']} fotos{extra} "
                "y esta completo. Ya pasamos tu pedido a produccion.")
    cabecera = (f"{saludo} Ya revisamos lo que nos enviaste para tus fotochecks. "
                "Para avanzar sin demoras necesitamos lo siguiente:\n")
    pie = (f"\nEl resto esta conforme ✅ ({rev['ok']} de {rev['total']} fotos listas). "
           "Apenas nos completes esto, tu pedido entra a produccion.")
    return cabecera + "\n" + "\n".join(lineas).rstrip() + "\n" + pie


# ---------- aviso de recorte dudoso ----------

def recorte_dudoso(alpha_fino, alpha_clasico, umbral=1.2):
    # Marca un recorte como DUDOSO cuando dos modelos distintos (el fino isnet y
    # el clasico u2net) discrepan mucho en la silueta: ahi es muy probable que
    # uno se haya equivocado (ropa clara confundida con la pared, pelo dificil).
    # Es el aviso para reprocesar ESA foto con "Foto dificil" (BiRefNet).
    # Una metrica de una sola imagen (contraste, "fuzz" del alfa) NO predice
    # esto de forma fiable (medido 2026-06-15: la camisa blanca de bajo
    # contraste salia bien y la beige de contraste medio salia rota); el
    # DESACUERDO entre dos modelos si separa limpio. Umbral 1.2% calibrado con
    # las 10 fotos reales: las 6 limpias dieron <=0.81%, las 3 problematicas
    # 1.48 / 2.64 / 4.93%.
    a1 = np.asarray(alpha_fino) >= 128
    a2 = np.asarray(alpha_clasico) >= 128
    union = int((a1 | a2).sum())
    if union < 500:
        return False
    inter = int((a1 & a2).sum())
    return (1.0 - inter / union) * 100.0 > umbral


# ---------- hoja de aprobacion (PDF) ----------
# Se dibuja con cv2 (NO con PIL.ImageDraw/ImageFont): esos submodulos de PIL no
# viajan dentro del .exe (solo esta PIL.Image) y rompian la hoja con un
# ImportError. REGLA DE ORO: todo lo que se use debe existir en el bundle, y
# cv2 si esta (lo usa todo el motor). La fuente Hershey de cv2 es menos "bonita"
# que Arial, pero la hoja es interna y se lee igual.

# Tildes/ñ -> letras simples: cv2.putText solo dibuja ASCII (fuentes Hershey).
_ACENTOS = str.maketrans(
    "áéíóúÁÉÍÓÚñÑüÜàèìòùÀÈÌÒÙâêîôûäëïöÿçÇ",
    "aeiouAEIOUnNuUaeiouAEIOUaeiouaeioycC")


def _ascii(texto):
    t = (texto or "").translate(_ACENTOS)
    return "".join(c if 32 <= ord(c) < 127 else "" for c in t)


def _texto(lienzo, txt, x, y_top, escala, grosor, color, ancho_max=None):
    # Dibuja texto estilo "esquina superior izquierda" como hacia PIL: cv2 ancla
    # en la base inferior, asi que bajamos por la altura del texto. Si se pasa
    # ancho_max, recorta el texto para que entre en la celda.
    txt = _ascii(txt)
    if ancho_max is not None:
        while txt and cv2.getTextSize(
                txt, cv2.FONT_HERSHEY_SIMPLEX, escala, grosor)[0][0] > ancho_max:
            txt = txt[:-1]
    if not txt:
        return
    (_, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, escala, grosor)
    cv2.putText(lienzo, txt, (int(x), int(y_top + th)),
                cv2.FONT_HERSHEY_SIMPLEX, escala, color, grosor, cv2.LINE_AA)


def hoja_aprobacion(archivos, destino_pdf, cliente="", nombres=None):
    # Grilla de miniaturas (foto final + codigo Y NOMBRE de la persona) en PDF.
    # Su valor real: que el CLIENTE confirme que cada foto corresponde a la
    # persona correcta ANTES de imprimir (el error de identidad es el caro).
    # 'nombres' = dict codigo -> nombre completo (del Excel), opcional.
    AN, AL = 1240, 1754  # A4 vertical a 150 dpi
    MARGEN, COLS = 60, 4
    celda_w = (AN - 2 * MARGEN - (COLS - 1) * 16) // COLS
    celda_h = int(celda_w * 1.05) + 34
    # Colores en orden RGB (el lienzo se interpreta como RGB al guardar).
    GRIS_OSC, GRIS, GRIS_CL = (30, 30, 30), (90, 90, 90), (200, 200, 200)
    BORDE, NEGRO, ROJO = (210, 210, 210), (40, 40, 40), (200, 60, 60)

    fecha = time.strftime("%d/%m/%Y")
    paginas = []
    por_pagina = COLS * max(1, (AL - 170 - MARGEN) // (celda_h + 14))
    for p0 in range(0, len(archivos), por_pagina):
        pag = np.full((AL, AN, 3), 255, np.uint8)
        _texto(pag, "DISECOD - Hoja de aprobacion de fotochecks",
               MARGEN, 42, 1.0, 2, GRIS_OSC)
        sub = f"{('Cliente: ' + cliente + '   |   ') if cliente else ''}Fecha: {fecha}   |   {len(archivos)} foto(s)"
        _texto(pag, sub, MARGEN, 88, 0.6, 1, GRIS)
        _texto(pag, "Revise que cada foto tenga el nombre/codigo correcto y "
               "responda APROBADO para imprimir.", MARGEN, 116, 0.6, 1, GRIS)
        cv2.line(pag, (MARGEN, 148), (AN - MARGEN, 148), GRIS_CL, 2)
        y = 170
        for i, ruta in enumerate(archivos[p0:p0 + por_pagina]):
            col = i % COLS
            if col == 0 and i > 0:
                y += celda_h + 14
            x = MARGEN + col * (celda_w + 16)
            try:
                im = Image.open(ruta).convert("RGBA")
                blanco = Image.new("RGBA", im.size, (255, 255, 255, 255))
                im = Image.alpha_composite(blanco, im).convert("RGB")
                im.thumbnail((celda_w - 8, celda_h - 38))
                arr = np.asarray(im)
                px = x + (celda_w - im.width) // 2
                py = y + 4
                pag[py:py + arr.shape[0], px:px + arr.shape[1]] = arr
                # El borde abraza la FOTO real, no la celda: con el borde
                # fijo, una foto menos alta que la celda quedaba con un
                # relleno blanco abajo DENTRO del marco y parecia que la
                # foto salio mal (feedback disenadora 2026-07-01).
                cv2.rectangle(pag, (px - 2, py - 2),
                              (px + arr.shape[1] + 1, py + arr.shape[0] + 1),
                              BORDE, 1)
            except Exception:
                _texto(pag, "(error)", x + 8, y + 8, 0.5, 1, ROJO)
            stem = Path(ruta).stem
            etiqueta = stem
            if nombres and stem in nombres:
                etiqueta = f"{stem} - {nombres[stem]}"
            _texto(pag, etiqueta, x + 4, y + celda_h - 26, 0.5, 1, NEGRO,
                   ancho_max=celda_w - 8)
        paginas.append(Image.fromarray(pag))
    destino_pdf = Path(destino_pdf)
    paginas[0].save(destino_pdf, "PDF", resolution=150.0,
                    save_all=True, append_images=paginas[1:])
    return destino_pdf


# ---------- carpeta por pedido ----------

def carpeta_pedido(base, cliente=""):
    # Carpeta propia para cada trabajo: pedidos/<fecha> <cliente>/. Asi las
    # fotos, firmas y hoja de aprobacion de un pedido quedan JUNTAS, en vez de
    # mezclarse todos los trabajos en una sola bolsa. Mismo dia + mismo
    # cliente = misma carpeta (los pedidos suelen llegar por partes).
    limpio = "".join(c for c in (cliente or "")
                     if c.isalnum() or c in " -_").strip()
    nombre = time.strftime("%Y-%m-%d") + (" " + limpio if limpio else " pedido")
    carpeta = Path(base) / "pedidos" / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


# ---------- registro de lotes (alimenta la recompra) ----------

def escribir_lote(archivo_csv, cliente, total, renombradas, carpeta):
    # Deja constancia de cada lote procesado en lotes.csv (junto al programa).
    # Ese archivo es ORO comercial: dice que cliente imprimio, cuanto y cuando
    # (para llamarlo cuando le toque renovar o entre personal nuevo).
    import csv
    archivo_csv = Path(archivo_csv)
    nuevo = not archivo_csv.exists()
    try:
        with open(archivo_csv, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            if nuevo:
                w.writerow(["fecha", "cliente", "fotos", "renombradas", "carpeta"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M"), cliente or "-",
                        total, renombradas, str(carpeta)])
    except Exception:
        pass  # el registro nunca debe tumbar el procesamiento

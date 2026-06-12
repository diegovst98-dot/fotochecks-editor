# Pedidos: revision previa de insumos (semaforo), mensaje al cliente, hoja de
# aprobacion en PDF y registro de lotes. Es la cara "comercial" del editor.
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import encuadre
import excel_codigos


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


def revisar_fotos(fotos, codigos=None, progreso=None):
    # Devuelve un resumen del estado del pedido SIN procesar nada.
    rev = {"total": len(fotos), "fotos": [], "sin_foto": [], "duplicados": [],
           "con_excel": bool(codigos)}
    usados = {}   # codigo -> primer archivo que lo uso
    emparejados = set()
    for i, ruta in enumerate(fotos, 1):
        problemas = []
        try:
            img = Image.open(ruta)
            img.load()
        except Exception:
            rev["fotos"].append({"nombre": ruta.name,
                                 "problemas": ["el archivo esta dañado o no es una foto"]})
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
            codigo, estado = excel_codigos.emparejar(ruta.stem, codigos)
            if estado in ("exacto", "aproximado", "ya_codigo") and codigo:
                if codigo in usados:
                    rev["duplicados"].append(
                        f"{ruta.name} y {usados[codigo]} parecen ser de la misma persona (codigo {codigo})")
                else:
                    usados[codigo] = ruta.name
                    emparejados.add(codigo)
            elif estado == "ambiguo":
                problemas.append("el nombre coincide con VARIAS personas del Excel")
            else:
                problemas.append("no encontramos este nombre en el Excel")
        rev["fotos"].append({"nombre": ruta.name, "problemas": problemas})
        if progreso:
            progreso(i)
    if codigos:
        for r in codigos:
            if r["codigo"] not in emparejados:
                rev["sin_foto"].append(f'{r["codigo"]} - {r["nombre"]}')
    rev["con_problema"] = [f for f in rev["fotos"] if f["problemas"]]
    rev["ok"] = rev["total"] - len(rev["con_problema"])
    return rev


def mensaje_para_cliente(rev):
    # Texto listo para copiar y mandar por WhatsApp al cliente.
    lineas = []
    if rev["sin_foto"]:
        lineas.append("*FALTAN LAS FOTOS de estas personas (estan en tu lista):*")
        lineas += [f"  - {p}" for p in rev["sin_foto"]]
        lineas.append("")
    borrosas = [f for f in rev["con_problema"]
                if any("borrosa" in p or "resolucion" in p or "dañado" in p
                       for p in f["problemas"])]
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
        return (f"¡Todo conforme! ✅ Revisamos las {rev['total']} fotos{extra} "
                "y esta completo. Ya pasamos tu pedido a produccion.")
    cabecera = ("Hola 👋 Ya revisamos lo que nos enviaste para tus fotochecks. "
                "Para avanzar sin demoras necesitamos lo siguiente:\n")
    pie = (f"\nEl resto esta conforme ✅ ({rev['ok']} de {rev['total']} fotos listas). "
           "Apenas nos completes esto, tu pedido entra a produccion.")
    return cabecera + "\n" + "\n".join(lineas).rstrip() + "\n" + pie


# ---------- hoja de aprobacion (PDF) ----------

def hoja_aprobacion(archivos, destino_pdf, cliente="", nombres=None):
    # Grilla de miniaturas (foto final + codigo Y NOMBRE de la persona) en PDF.
    # Su valor real: que el CLIENTE confirme que cada foto corresponde a la
    # persona correcta ANTES de imprimir (el error de identidad es el caro).
    # 'nombres' = dict codigo -> nombre completo (del Excel), opcional.
    from PIL import ImageDraw, ImageFont
    AN, AL = 1240, 1754  # A4 vertical a 150 dpi
    MARGEN, COLS = 60, 4
    celda_w = (AN - 2 * MARGEN - (COLS - 1) * 16) // COLS
    celda_h = int(celda_w * 1.05) + 34
    try:
        F_TIT = ImageFont.truetype("arialbd.ttf", 30)
        F_SUB = ImageFont.truetype("arial.ttf", 19)
        F_PIE = ImageFont.truetype("arial.ttf", 17)
    except Exception:
        F_TIT = F_SUB = F_PIE = ImageFont.load_default()

    fecha = time.strftime("%d/%m/%Y")
    paginas = []
    por_pagina = COLS * max(1, (AL - 170 - MARGEN) // (celda_h + 14))
    for p0 in range(0, len(archivos), por_pagina):
        pag = Image.new("RGB", (AN, AL), (255, 255, 255))
        d = ImageDraw.Draw(pag)
        d.text((MARGEN, 42), "DISECOD - Hoja de aprobacion de fotochecks",
               fill=(30, 30, 30), font=F_TIT)
        sub = f"{('Cliente: ' + cliente + '   |   ') if cliente else ''}Fecha: {fecha}   |   {len(archivos)} foto(s)"
        d.text((MARGEN, 86), sub, fill=(90, 90, 90), font=F_SUB)
        d.text((MARGEN, 114),
               "Revise que cada foto tenga el nombre/codigo correcto y responda "
               "APROBADO para imprimir.", fill=(90, 90, 90), font=F_SUB)
        d.line((MARGEN, 148, AN - MARGEN, 148), fill=(200, 200, 200), width=2)
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
                pag.paste(im, (x + (celda_w - im.width) // 2, y + 4))
                d.rectangle((x, y, x + celda_w, y + celda_h - 30),
                            outline=(210, 210, 210), width=1)
            except Exception:
                d.text((x + 8, y + 8), "(error)", fill=(200, 60, 60), font=F_PIE)
            stem = Path(ruta).stem
            etiqueta = stem
            if nombres and stem in nombres:
                etiqueta = f"{stem} - {nombres[stem]}"
            d.text((x + 4, y + celda_h - 24), etiqueta[:30],
                   fill=(40, 40, 40), font=F_PIE)
        paginas.append(pag)
    destino_pdf = Path(destino_pdf)
    paginas[0].save(destino_pdf, "PDF", resolution=150.0,
                    save_all=True, append_images=paginas[1:])
    return destino_pdf


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

# Emparejado de fotos con codigos (Excel).
# CardPresso enlaza cada foto por el codigo en el nombre del archivo. El cliente
# manda las fotos con nombre y apellido; el Excel tiene codigo + nombre. Aqui se
# empareja el nombre del archivo contra el Excel y se devuelve el codigo para
# renombrar la salida. Conservador a proposito: solo empareja cuando esta seguro
# (poner un codigo equivocado en un fotocheck es grave); las dudas se marcan.
import re
import unicodedata


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


def _es_codigo(v):
    s = str(v).strip()
    digitos = re.sub(r"[^0-9]", "", s)
    # "parece codigo" si es mayormente digitos (ej. 5333467, 12345678, A-102)
    return len(digitos) >= 4 and len(digitos) >= len(re.sub(r"\s", "", s)) - 2


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

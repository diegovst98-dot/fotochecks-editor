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


def _dist(a, b):
    # Distancia de edicion (Levenshtein) en Python puro: cuantas letras cambian
    # de 'a' a 'b'. Sin dependencias externas (debe viajar dentro del .exe).
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if not la:
        return lb
    if not lb:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[lb]


def _token_match(x, y):
    # ¿son la misma palabra (igual o typo chico)? Devuelve la distancia si la
    # tolera, o None. Tolerancia 1 para palabras cortas, 2 para largas (>6).
    if x == y:
        return 0
    tol = 1 if min(len(x), len(y)) <= 6 else 2
    d = _dist(x, y)
    return d if d <= tol else None


def _cobertura(toks_a, toks_b):
    # Empareja greedy cada palabra de A con una de B "casi igual". Devuelve
    # (cuantas emparejaron, suma de letras cambiadas).
    libres = list(toks_b)
    n = edits = 0
    for x in toks_a:
        best = None
        for i, y in enumerate(libres):
            d = _token_match(x, y)
            if d is not None and (best is None or d < best[1]):
                best = (i, d)
        if best is not None:
            n += 1
            edits += best[1]
            libres.pop(best[0])
    return n, edits


def _puntuar(norm, toks, se, r):
    # Puntua un registro del Excel contra la foto. 'se' = nombre de la foto sin
    # espacios. Combina cobertura de palabras y parecido "sin espacios" (esto
    # ultimo resuelve merges/splits tipo CarmenCondori = Carmen Condori).
    na, nb = len(toks), len(r["tokens"])
    nmin = min(na, nb) or 1
    n1, e1 = _cobertura(toks, r["tokens"])
    n2, e2 = _cobertura(r["tokens"], toks)
    cubierto = max(n1, n2) >= nmin           # el lado mas chico calza entero
    edits = e1 if na <= nb else e2
    se_r = r["norm"].replace(" ", "")
    d_se = _dist(se, se_r)
    score = max(1.0 - d_se / max(len(se), len(se_r), 1),
                (max(n1, n2) / nmin) - 0.001 * edits)
    return {"r": r, "score": score, "cubierto": cubierto, "edits": edits, "d_se": d_se}


# Palabras de encabezado que delatan que columna es cada cosa. Permiten leer
# Excels del cliente con CUALQUIER numero de columnas (no solo 2): codigo, nombre
# y un "detalle" (cargo/sede/empresa) para distinguir homonimos en la UI.
_HDR_CODIGO = re.compile(r"\b(dni|codigo|c[oó]digo|carnet|carne|c\.?e\.?|documento|doc|id)\b", re.I)
_HDR_NOMBRE = re.compile(r"\b(nombre|trabajador|apellido|persona|colaborador|empleado|alumno|estudiante|titular)\b", re.I)
_HDR_DETALLE = re.compile(r"\b(cargo|puesto|area|área|sede|empresa|oficina|sucursal|gerencia|departamento|local|planta|rol)\b", re.I)


def cargar_codigos(ruta_excel):
    # Lee el Excel del cliente (cualquier nº de columnas) y devuelve registros
    # {codigo, nombre, detalle, norm, tokens}. Detecta las columnas por el
    # ENCABEZADO (DNI/codigo, nombre/trabajador, cargo/sede/empresa); si no hay
    # encabezado reconocible, cae al modo simple (columna con digitos = codigo,
    # primera de texto = nombre). 'detalle' es solo para mostrar (distinguir
    # homonimos); NO se usa para emparejar.
    import openpyxl
    wb = openpyxl.load_workbook(ruta_excel, data_only=True)
    ws = wb.active
    filas = [list(f) for f in ws.iter_rows(values_only=True)
             if f and any(c not in (None, "") for c in f)]
    if not filas:
        return []
    ncol = max(len(f) for f in filas)
    for f in filas:
        f += [None] * (ncol - len(f))

    encabezado = filas[0]
    hay_hdr = not any(_es_codigo(c) for c in encabezado if c not in (None, ""))
    col_codigo = col_nombre = None
    cols_detalle = []
    if hay_hdr:
        for j, h in enumerate(encabezado):
            ht = str(h or "")
            if col_codigo is None and _HDR_CODIGO.search(ht):
                col_codigo = j
            elif col_nombre is None and _HDR_NOMBRE.search(ht):
                col_nombre = j
            elif _HDR_DETALLE.search(ht):
                cols_detalle.append(j)
        datos = filas[1:]
    else:
        datos = filas

    if col_codigo is None:  # sin encabezado util: la columna con mas "codigos"
        punt = [sum(1 for f in datos if _es_codigo(f[j])) for j in range(ncol)]
        col_codigo = max(range(ncol), key=lambda j: punt[j]) if any(punt) else None
    if col_nombre is None:  # primera columna de texto distinta del codigo
        def _es_texto(j):
            return sum(1 for f in datos if _normalizar(f[j])) >= max(1, len(datos) // 2)
        for j in range(ncol):
            if j != col_codigo and _es_texto(j):
                col_nombre = j
                break
    if col_codigo is None or col_nombre is None:
        return []

    registros = []
    for f in datos:
        codigo = str(f[col_codigo]).strip() if f[col_codigo] not in (None, "") else ""
        nombre = str(f[col_nombre]).strip() if f[col_nombre] not in (None, "") else ""
        if not re.sub(r"[^0-9]", "", codigo) or not _normalizar(nombre):
            continue  # salta encabezado sobrante y filas sin codigo/nombre
        detalle = " · ".join(str(f[j]).strip() for j in cols_detalle
                             if f[j] not in (None, "")) if cols_detalle else ""
        registros.append({
            "codigo": codigo,
            "nombre": nombre,
            "detalle": detalle,
            "norm": _normalizar(nombre),
            "tokens": _tokens(nombre),
        })
    return registros


def dni_sospechoso(codigo):
    # Devuelve un motivo si el DNI/codigo se ve raro (para AVISAR, no corregir):
    # ceros perdidos por Excel, letras, o longitudes fuera de lo normal. None = ok.
    d = str(codigo).strip()
    if not d:
        return "vacio"
    if not d.isdigit():
        return "tiene letras o simbolos"
    if len(d) == 7:
        return "7 digitos (¿le falta un 0 inicial?)"
    if len(d) < 7:
        return f"{len(d)} digitos (muy corto)"
    if len(d) > 8:
        return f"{len(d)} digitos (largo: ¿C.E. o documento extranjero?)"
    return None


def dni_sospechosos(registros):
    # Lista [(codigo, nombre, motivo)] de los registros con DNI dudoso.
    out = []
    for r in registros:
        motivo = dni_sospechoso(r["codigo"])
        if motivo:
            out.append((r["codigo"], r["nombre"], motivo))
    return out


def emparejar_detalle(stem, registros):
    # Cruza el nombre del archivo contra el Excel y devuelve:
    #   {"codigo": str|None, "estado": str, "candidatos": [registro, ...]}
    # estados: ya_codigo / exacto / aproximado (auto) / sugerencia (proponer) /
    #          ambiguo (elegir) / sin_match.
    # Seguridad: solo auto-empareja un candidato unico y casi identico cuando
    # gana por MARGEN claro al 2do (jamas fusiona dos personas parecidas).
    norm = _normalizar(stem)
    toks = set(norm.split())
    se = norm.replace(" ", "")

    solo = re.sub(r"[^0-9]", "", stem)
    if solo and norm == solo:
        for r in registros:
            if re.sub(r"[^0-9]", "", r["codigo"]) == solo:
                return {"codigo": r["codigo"], "estado": "ya_codigo", "candidatos": [r]}
        return {"codigo": stem.strip(), "estado": "ya_codigo", "candidatos": []}

    exactos = [r for r in registros if r["norm"] == norm or r["tokens"] == toks]
    if len(exactos) == 1:
        return {"codigo": exactos[0]["codigo"], "estado": "exacto", "candidatos": exactos}
    if len(exactos) > 1:
        return {"codigo": None, "estado": "ambiguo", "candidatos": exactos}

    cand = sorted((_puntuar(norm, toks, se, r) for r in registros),
                  key=lambda c: -c["score"])
    if not cand:
        return {"codigo": None, "estado": "sin_match", "candidatos": []}
    mejor = cand[0]
    segundo = cand[1] if len(cand) > 1 else None
    casi = (mejor["d_se"] <= 1) or (mejor["cubierto"] and mejor["edits"] <= 1)
    margen = segundo is None or (mejor["score"] - segundo["score"]) >= 0.15
    seg_lejos = segundo is None or segundo["score"] < 0.8

    if casi and margen and seg_lejos and mejor["score"] >= 0.85:
        return {"codigo": mejor["r"]["codigo"], "estado": "aproximado",
                "candidatos": [mejor["r"]]}
    if mejor["score"] >= 0.6 and margen and seg_lejos:
        return {"codigo": mejor["r"]["codigo"], "estado": "sugerencia",
                "candidatos": [mejor["r"]]}
    parecidos = [c for c in cand if c["score"] >= 0.6]
    if len(parecidos) >= 2:
        return {"codigo": None, "estado": "ambiguo",
                "candidatos": [c["r"] for c in parecidos[:5]]}
    if mejor["score"] >= 0.6:
        return {"codigo": mejor["r"]["codigo"], "estado": "sugerencia",
                "candidatos": [mejor["r"]]}
    return {"codigo": None, "estado": "sin_match", "candidatos": []}


def emparejar(stem, registros):
    # Envoltura que mantiene la firma (codigo, estado) usada por revisar_fotos,
    # el flujo de procesado y el candado de tests.
    d = emparejar_detalle(stem, registros)
    return d["codigo"], d["estado"]

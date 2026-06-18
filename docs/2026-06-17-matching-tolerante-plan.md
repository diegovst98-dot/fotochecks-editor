# Matching tolerante a variaciones — Plan de implementación (Fase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el editor reconozca solo los typos de un nombre único (Aroyo→Arroyo, CarmenCondori→Carmen Condori) y deje los nombres realmente duplicados marcados para elegir a mano, sin riesgo de emparejar a la persona equivocada.

**Architecture:** Se reescribe el clasificador `emparejar` de `codigo/excel_codigos.py` para puntuar cada registro del Excel por similitud (distancia de edición por palabra + comparación sin espacios) y clasificar en 4 estados con una regla de margen contra el 2º mejor: `exacto`/`aproximado` (auto), `sugerencia` (proponer, Fase 2), `ambiguo` (elegir, Fase 2), `sin_match`. La lógica vive en una nueva `emparejar_detalle()` que devuelve candidatos; `emparejar()` queda como envoltura que mantiene su firma `(codigo, estado)`. Cero dependencias nuevas (solo `re`/`unicodedata`, ya importadas) → se publica por auto-update sin reconstruir el `.exe`.

**Tech Stack:** Python 3.12 (stdlib pura), harness de tests propio del proyecto (`tests/correr_tests.py`, función `check()`).

---

## Estructura de archivos

- **Modificar** `codigo/excel_codigos.py` — agregar helpers `_dist`, `_token_match`, `_cobertura`, `_puntuar`; agregar `emparejar_detalle()`; reescribir `emparejar()` como envoltura. (Responsable del cruce nombre↔código.)
- **Modificar** `codigo/editar_fotos.py:32-33` — reexportar también `emparejar_detalle`.
- **Crear** `tests/test_matching.py` — test rápido y autónomo (sin modelo IA ni exe) para el loop TDD; corre en <1s.
- **Modificar** `tests/correr_tests.py` (sección `[2/6] Emparejado con Excel`) — sumar asserts del comportamiento nuevo al candado de publicación.

**Cómo correr los tests:**
- Rápido (TDD): `python tests\test_matching.py`  → imprime OK/FALLA, exit 1 si algo falla.
- Candado completo (antes de publicar): `python tests\correr_tests.py` (carga el modelo, ~30 s).

> Regla del proyecto: NO publicar (`publicar.py`) hasta que el candado esté verde y Diego confirme. Este plan llega hasta "candado verde"; publicar es decisión aparte.

---

### Task 1: Helper de distancia de edición (`_dist`)

**Files:**
- Modify: `codigo/excel_codigos.py` (agregar función tras `_es_codigo`)
- Create/Test: `tests/test_matching.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_matching.py` con:

```python
# Test rapido y autonomo del matching (sin modelo IA ni exe). Estilo del proyecto:
# imprime OK/FALLA y devuelve exit 1 si algo falla. Correr: python tests\test_matching.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "codigo"))

import excel_codigos as ec

fallas = []
def check(nombre, cond, detalle=""):
    print(("  OK   " if cond else "  FALLA ") + nombre + ("" if cond else f"  {detalle}"))
    if not cond:
        fallas.append(nombre)

# ---- Task 1: _dist (Levenshtein) ----
check("dist iguales", ec._dist("garcia", "garcia") == 0)
check("dist 1 sustitucion", ec._dist("garcia", "garzia") == 1)
check("dist 1 insercion", ec._dist("cristian", "cristhian") == 1)
check("dist vacio", ec._dist("", "abc") == 3)
check("dist sin espacios identico", ec._dist("carmencondori", "carmencondori") == 0)

if __name__ == "__main__":
    print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLA(S)'}")
    sys.exit(1 if fallas else 0)
```

- [ ] **Step 2: Correr el test y verque falle**

Run: `python tests\test_matching.py`
Expected: FALLA / AttributeError: module 'excel_codigos' has no attribute '_dist'

- [ ] **Step 3: Implementar `_dist` en `excel_codigos.py`**

Agregar después de `_es_codigo()` (antes de `cargar_codigos`):

```python
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
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python tests\test_matching.py`
Expected: las 5 líneas de `dist` en OK.

- [ ] **Step 5: Commit**

```bash
git add codigo/excel_codigos.py tests/test_matching.py
git commit -m "feat(matching): distancia de edicion _dist (Levenshtein puro)"
```

---

### Task 2: Similitud por palabra y por registro (`_token_match`, `_cobertura`, `_puntuar`)

**Files:**
- Modify: `codigo/excel_codigos.py`
- Test: `tests/test_matching.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_matching.py` (antes del bloque `if __name__`):

```python
# ---- Task 2: _token_match / _cobertura / _puntuar ----
check("token typo corto (<=6) tolera 1", ec._token_match("aroyo", "arroyo") == 1)
check("token typo largo tolera 2", ec._token_match("giancarlos", "giancarlo") == 1)
check("token distinto = None", ec._token_match("juan", "maria") is None)
ig, ca = ec._cobertura({"cielo", "aroyo"}, {"cielo", "arroyo"})
check("cobertura 2 tokens, 1 edit", ig == 2 and ca == 1, f"{ig}/{ca}")

def _reg(cod, nom):
    return {"codigo": str(cod), "nombre": nom, "norm": ec._normalizar(nom), "tokens": ec._tokens(nom)}

r = _reg("1", "Cielo Arroyo")
p = ec._puntuar(ec._normalizar("Cielo Aroyo"), ec._tokens("Cielo Aroyo"),
                ec._normalizar("Cielo Aroyo").replace(" ", ""), r)
check("puntua typo alto (>=0.85)", p["score"] >= 0.85, str(p["score"]))
check("puntua typo casi-identico (edits<=1 o d_se<=1)", p["edits"] <= 1 or p["d_se"] <= 1, str(p))
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python tests\test_matching.py`
Expected: FALLA en `token typo...` (AttributeError: `_token_match`).

- [ ] **Step 3: Implementar los 3 helpers en `excel_codigos.py`**

Agregar después de `_dist`:

```python
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
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python tests\test_matching.py`
Expected: los bloques de Task 1 y Task 2 en OK.

- [ ] **Step 5: Commit**

```bash
git add codigo/excel_codigos.py tests/test_matching.py
git commit -m "feat(matching): similitud por palabra y por registro (_token_match/_cobertura/_puntuar)"
```

---

### Task 3: `emparejar_detalle` + reescribir `emparejar`

**Files:**
- Modify: `codigo/excel_codigos.py` (reemplazar el cuerpo de `emparejar`)
- Test: `tests/test_matching.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_matching.py` (antes del `if __name__`):

```python
# ---- Task 3: bandas de emparejar ----
H = [_reg("1001", "Juan Perez Gomez"), _reg("1002", "Maria Lopez Diaz"),
     _reg("1003", "Maria Lopez Castro"), _reg("1004", "Ana Torres Vega"),
     _reg("1005", "Jorge Quispe Mamani")]
c, e = ec.emparejar("Juan Perez Gomez", H)
check("exacto", c == "1001" and e == "exacto", f"{c}/{e}")
c, e = ec.emparejar("ana torres", H)
check("aproximado por subset", c == "1004" and e == "aproximado", f"{c}/{e}")
c, e = ec.emparejar("Maria Lopez", H)
check("ambiguo (2 Marias)", e == "ambiguo", f"{c}/{e}")
c, e = ec.emparejar("Pedro Inexistente", H)
check("sin_match", e == "sin_match", f"{c}/{e}")

# typos de una persona unica -> auto (aproximado)
T = [_reg("76662949", "Cielo Arroyo"), _reg("72398280", "Estefania Oscco"),
     _reg("46686861", "Cristhian Camargo"), _reg("72492436", "Giancarlo Cuba"),
     _reg("75345080", "Mary Carmen Condori"), _reg("99", "Pedro Quispe Soto")]
for stem, cod in [("Cielo Aroyo", "76662949"), ("Estefania Ossco", "72398280"),
                  ("Cristian Camargo", "46686861"), ("Giancarlos Cuba", "72492436"),
                  ("Mary CarmenCondori", "75345080")]:
    c, e = ec.emparejar(stem, T)
    check(f"typo auto: {stem}", c == cod and e == "aproximado", f"{c}/{e}")

# negativo de seguridad: nombre parcial compartido por 2 personas -> NO auto
NEG = [_reg("2001", "Ana Torres Vega"), _reg("2002", "Ana Flores Vega"),
       _reg("2003", "Carlos Mota Ruiz")]
c, e = ec.emparejar("Ana Vega", NEG)
check("negativo: parcial compartido = ambiguo", e == "ambiguo", f"{c}/{e}")

# detalle: candidatos disponibles para la UI (Fase 2)
d = ec.emparejar_detalle("Maria Lopez", H)
check("detalle ambiguo lista 2 candidatos", d["estado"] == "ambiguo" and len(d["candidatos"]) == 2,
      str(d))
check("emparejar = envoltura de detalle",
      ec.emparejar("Juan Perez Gomez", H) == (ec.emparejar_detalle("Juan Perez Gomez", H)["codigo"],
                                              ec.emparejar_detalle("Juan Perez Gomez", H)["estado"]))
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python tests\test_matching.py`
Expected: FALLA en `detalle...` (AttributeError: `emparejar_detalle`) y/o en `typo auto:` (el `emparejar` viejo da `sin_match`).

- [ ] **Step 3: Reemplazar `emparejar` por `emparejar_detalle` + envoltura**

En `excel_codigos.py`, **borrar la función `emparejar` actual completa** (desde `def emparejar(stem, registros):` hasta su `return None, "sin_match"`) y poner en su lugar:

```python
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
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python tests\test_matching.py`
Expected: `TODO OK` (todas las líneas en OK).

- [ ] **Step 5: Commit**

```bash
git add codigo/excel_codigos.py tests/test_matching.py
git commit -m "feat(matching): emparejar_detalle con 4 bandas + regla de margen; emparejar como envoltura"
```

---

### Task 4: Reexportar `emparejar_detalle` desde `editar_fotos.py`

**Files:**
- Modify: `codigo/editar_fotos.py:32-33`

- [ ] **Step 1: Editar el import**

Reemplazar:

```python
from excel_codigos import (_normalizar, _tokens, _es_codigo,
                           cargar_codigos, emparejar)
```

por:

```python
from excel_codigos import (_normalizar, _tokens, _es_codigo,
                           cargar_codigos, emparejar, emparejar_detalle)
```

- [ ] **Step 2: Verificar que compila e importa**

Run: `python -c "import sys; sys.path.insert(0, 'codigo'); import editar_fotos; print(editar_fotos.emparejar_detalle)"`
Expected: imprime `<function emparejar_detalle at ...>` sin error.

- [ ] **Step 3: Commit**

```bash
git add codigo/editar_fotos.py
git commit -m "chore: reexportar emparejar_detalle para la UI de Revisar pedido (Fase 2)"
```

---

### Task 5: Sumar el comportamiento nuevo al candado (`correr_tests.py`)

**Files:**
- Modify: `tests/correr_tests.py` (sección `[2/6] Emparejado con Excel`, después de la línea `check("sin match detectado", ...)`)

- [ ] **Step 1: Agregar asserts del comportamiento nuevo**

En `correr_tests.py`, justo después de:

```python
    c, e = core.emparejar("Pedro Inexistente", codigos)
    check("sin match detectado", not c or e not in ("exacto", "aproximado"), f"{c}/{e}")
```

agregar:

```python
    # typos de una persona unica -> auto (aproximado); ver docs/2026-06-17-matching-*
    wb2 = Workbook(); ws2 = wb2.active
    ws2.append(["Codigo", "Nombre"])
    for fila in (("2001", "Cielo Arroyo"), ("2002", "Cristhian Camargo"),
                 ("2003", "Mary Carmen Condori"), ("2004", "Ana Flores Vega"),
                 ("2005", "Ana Torres Vega")):
        ws2.append(fila)
    xls2 = TMP / "personal2.xlsx"; wb2.save(xls2)
    cods2 = core.cargar_codigos(xls2)
    c, e = core.emparejar("Cielo Aroyo", cods2)
    check("typo auto: Aroyo->Arroyo", c == "2001" and e == "aproximado", f"{c}/{e}")
    c, e = core.emparejar("Cristian Camargo", cods2)
    check("typo auto: Cristian->Cristhian", c == "2002" and e == "aproximado", f"{c}/{e}")
    c, e = core.emparejar("Mary CarmenCondori", cods2)
    check("typo auto: CarmenCondori->Carmen Condori", c == "2003" and e == "aproximado", f"{c}/{e}")
    c, e = core.emparejar("Ana Vega", cods2)
    check("seguridad: parcial compartido NO se auto-empareja", e == "ambiguo", f"{c}/{e}")
```

- [ ] **Step 2: Correr el candado completo**

Run: `python tests\correr_tests.py`
Expected: sección `[2/6]` con todos los `OK` (incluidos los 4 nuevos); el resto del candado igual que antes. Línea final `RESULTADO: TODO OK`.

> Si `[5/6]` (doradas) o `[1b]` (exe) fallan por falta de modelo/`dist` en esta PC, NO es por este cambio; el matching debe estar todo en OK. Publicar solo se hace en la PC que sí tiene `dist/` y con el candado entero verde.

- [ ] **Step 3: Commit**

```bash
git add tests/correr_tests.py
git commit -m "test(candado): cubre typos-auto y el caso de seguridad de nombres parecidos"
```

---

### Task 6: Verificación final

- [ ] **Step 1: Correr ambos test suites**

Run: `python tests\test_matching.py` → `TODO OK`
Run: `python tests\correr_tests.py` → sección `[2/6]` 100% OK.

- [ ] **Step 2: Confirmar distribución sobre un Excel de 2 columnas real (opcional, manual)**

Con el Excel `GFP_Nombre_DNI.xlsx`: 252 fotos deben dar ~236 exacto + ~14 aproximado + 2 ambiguo (los 2 Ricardo Flores), 0 `sin_match`. Esto valida que ningún nombre distinto se fusionó.

- [ ] **Step 3: Listo para Fase 2 / publicación**

Fin de Fase 1. NO publicar aún: la publicación (`publicar.py`) y la UI de confirmar/elegir son Fase 2, y se hacen con Diego.

---

## Self-Review (cobertura vs spec)

- ✅ **Híbrido (auto + sugerencia):** estados `aproximado` (auto) y `sugerencia` (proponer) implementados en `emparejar_detalle` (Task 3).
- ✅ **Elegir a mano (duplicados):** `ambiguo` con lista de `candidatos` (Task 3); reexpuesto para la UI (Task 4).
- ✅ **Regla de seguridad (margen vs 2º):** `margen` + `seg_lejos` en Task 3; test negativo en Tasks 3 y 5.
- ✅ **Sin espacios (CarmenCondori):** `d_se` en `_puntuar` (Task 2), test en Tasks 2/3/5.
- ✅ **Sin dependencias nuevas:** todo `re`/`unicodedata`/stdlib; nada que reconstruya el `.exe`.
- ✅ **No rompe lo existente:** `emparejar` mantiene firma `(codigo, estado)`; tests viejos del candado intactos.
- ✅ **Tests:** mantiene `ambiguo` (2 Marías) y `sin_match` (Pedro); agrega typos-auto + negativo de seguridad.
- ⏭️ **Fuera de Fase 1 (Fase 2):** UI en "Revisar pedido" (Sí/No y elegir), y que `revisar_fotos`/`mensaje_para_cliente` usen `sugerencia`/`ambiguo` resueltos para limpiar el mensaje al cliente.

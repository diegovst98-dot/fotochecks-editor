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

def _reg(cod, nom):
    return {"codigo": str(cod), "nombre": nom, "norm": ec._normalizar(nom), "tokens": ec._tokens(nom)}

# ---- Task 1: _dist (Levenshtein) ----
check("dist iguales", ec._dist("garcia", "garcia") == 0)
check("dist 1 sustitucion", ec._dist("garcia", "garzia") == 1)
check("dist 1 insercion", ec._dist("cristian", "cristhian") == 1)
check("dist vacio", ec._dist("", "abc") == 3)
check("dist sin espacios identico", ec._dist("carmencondori", "carmencondori") == 0)

# ---- Task 2: _token_match / _cobertura / _puntuar ----
check("token typo corto (<=6) tolera 1", ec._token_match("aroyo", "arroyo") == 1)
check("token typo largo tolera 2", ec._token_match("giancarlos", "giancarlo") == 1)
check("token distinto = None", ec._token_match("juan", "maria") is None)
ig, ca = ec._cobertura({"cielo", "aroyo"}, {"cielo", "arroyo"})
check("cobertura 2 tokens, 1 edit", ig == 2 and ca == 1, f"{ig}/{ca}")

r = _reg("1", "Cielo Arroyo")
p = ec._puntuar(ec._normalizar("Cielo Aroyo"), ec._tokens("Cielo Aroyo"),
                ec._normalizar("Cielo Aroyo").replace(" ", ""), r)
check("puntua typo alto (>=0.85)", p["score"] >= 0.85, str(p["score"]))
check("puntua typo casi-identico (edits<=1 o d_se<=1)", p["edits"] <= 1 or p["d_se"] <= 1, str(p))

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
check("detalle ambiguo lista 2 candidatos", d["estado"] == "ambiguo" and len(d["candidatos"]) == 2, str(d))
check("emparejar = envoltura de detalle",
      ec.emparejar("Juan Perez Gomez", H) == (ec.emparejar_detalle("Juan Perez Gomez", H)["codigo"],
                                              ec.emparejar_detalle("Juan Perez Gomez", H)["estado"]))

# ---- P2: cargar_codigos multi-columna + detalle ----
import openpyxl, tempfile, os
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["EMPRESA", "TRABAJADOR", "CARGO", "SEDE", "DNI"])
ws.append(["ACME", "Ricardo Flores", "Supervisor", "CAÑETE", "73217258"])
ws.append(["ACME", "Ricardo Flores", "CEO", "LIMA", "15726725"])
ws.append(["ACME", "Ana Torres Vega", "Operaria", "ICA", "45678901"])
_p = os.path.join(tempfile.gettempdir(), "tm_codigos.xlsx"); wb.save(_p)
_regs = ec.cargar_codigos(_p)
check("cargar_codigos multi-col: 3 registros", len(_regs) == 3, str(len(_regs)))
check("cargar_codigos: codigo = DNI",
      {r["codigo"] for r in _regs} == {"73217258", "15726725", "45678901"}, str(_regs))
check("cargar_codigos: detalle distingue homonimos",
      any("CEO" in r["detalle"] for r in _regs) and any("Supervisor" in r["detalle"] for r in _regs),
      str([r["detalle"] for r in _regs]))
# sigue emparejando bien con el Excel multi-col
c, e = ec.emparejar("Ana Torres Vega", _regs)
check("multi-col: empareja exacto", c == "45678901" and e == "exacto", f"{c}/{e}")
c, e = ec.emparejar("Ricardo Flores", _regs)
check("multi-col: homonimo = ambiguo", e == "ambiguo", f"{c}/{e}")

# ---- P3: dni_sospechoso ----
check("dni ok (8 dig)", ec.dni_sospechoso("70397937") is None)
check("dni 7 dig avisa", ec.dni_sospechoso("7877823") is not None)
check("dni con letra avisa", ec.dni_sospechoso("N21791962") is not None)
check("dni largo avisa (CE)", ec.dni_sospechoso("101000092") is not None)
sosp = ec.dni_sospechosos([_reg("70397937", "Ok Persona"),
                           {"codigo": "7877823", "nombre": "Raro Uno"}])
check("dni_sospechosos lista solo los raros", len(sosp) == 1 and sosp[0][0] == "7877823", str(sosp))

if __name__ == "__main__":
    print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLA(S)'}")
    sys.exit(1 if fallas else 0)

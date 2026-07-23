# Test rapido y autonomo de la "hoja de tamano fijo" de las firmas (sin modelo IA
# ni exe). Verifica lo que pidio Mirza (2026-07-23): que TODAS las firmas salgan
# del mismo tamano, con el trazo agrandado y centrado, sin deformarse.
# Correr: python tests\test_hoja_firma.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "codigo"))

import numpy as np
import cv2
from firmas import _ajustar_a_hoja, HOJA_ANCHO, HOJA_ALTO

fallas = []
def check(nombre, cond, detalle=""):
    print(("  OK   " if cond else "  FALLA ") + nombre + ("" if cond else f"  {detalle}"))
    if not cond:
        fallas.append(nombre)

def caja(a):
    ys, xs = np.where(a > 0.05)
    return xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1

def rampa(a):
    b = (a > 0.5).astype(np.uint8)
    borde = b - cv2.erode(b, np.ones((3, 3), np.uint8))
    return ((a > 0.05) & (a < 0.95)).sum() / max(borde.sum(), 1)

# Tres trazos de proporciones muy distintas, como las firmas reales que mando
# Mirza (alargada 2.9, media 1.5, casi cuadrada 1.3).
trazos = {}
for nombre, (w, h) in {"alargada": (400, 136), "media": (211, 138),
                       "cuadrada": (172, 133)}.items():
    a = np.zeros((h + 20, w + 20), np.float32)
    cv2.line(a, (10, h), (w + 10, 10), 1.0, 3, cv2.LINE_AA)
    cv2.circle(a, (w // 2, h // 2), min(w, h) // 3, 1.0, 3, cv2.LINE_AA)
    trazos[nombre] = a

salidas = {n: _ajustar_a_hoja(a, HOJA_ANCHO, HOJA_ALTO) for n, a in trazos.items()}

# 1) Lo central del pedido: TODAS del mismo tamano.
check("todas salen del mismo tamano",
      all(s.shape == (HOJA_ALTO, HOJA_ANCHO) for s in salidas.values()),
      str([s.shape for s in salidas.values()]))

for n, s in salidas.items():
    x, y, w, h = caja(s)
    _, _, orig_w, orig_h = caja(trazos[n])   # el TRAZO, no el lienzo que lo contiene

    # 2) No se deforma: la proporcion del trazo se respeta (una firma estirada se nota).
    prop_in, prop_out = orig_w / orig_h, w / h
    check(f"{n}: no se deforma", abs(prop_in - prop_out) / prop_in < 0.03,
          f"entra {prop_in:.2f} sale {prop_out:.2f}")

    # 3) Se agranda hasta llenar la hoja por el lado que topa primero (>=80%).
    check(f"{n}: llena la hoja", max(w / HOJA_ANCHO, h / HOJA_ALTO) > 0.80,
          f"ocupa {100*w/HOJA_ANCHO:.0f}%x{100*h/HOJA_ALTO:.0f}%")

    # 4) No desborda y queda centrado.
    check(f"{n}: cabe entero en la hoja", w <= HOJA_ANCHO and h <= HOJA_ALTO,
          f"{w}x{h}")
    check(f"{n}: centrado", abs((HOJA_ANCHO - w) / 2 - x) <= 2 and
          abs((HOJA_ALTO - h) / 2 - y) <= 2, f"x={x} y={y}")

    # 5) El borde no queda blandito al agrandar (referencia de Mirza: 0.10;
    #    firmas crudas: 0.07-0.24). Sin re-apretar el alfa se va a ~3.6 px.
    check(f"{n}: borde firme al agrandar", rampa(s) < 0.35, f"rampa {rampa(s):.2f}")

# 6) La medida por defecto es la de la referencia de Mirza: 8.60 x 5.40 cm @300dpi.
check("hoja por defecto = 1016x638 px (8.60 x 5.40 cm a 300 DPI)",
      (HOJA_ANCHO, HOJA_ALTO) == (1016, 638), f"{HOJA_ANCHO}x{HOJA_ALTO}")

if __name__ == "__main__":
    print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLA(S)'}")
    sys.exit(1 if fallas else 0)

# Test rapido y autonomo de _alfa_apretado (sin modelo IA ni exe).
# Correr: python tests\test_alfa.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "codigo"))

import numpy as np
import cv2
from PIL import Image
from retoque import _alfa_apretado

fallas = []
def check(nombre, cond, detalle=""):
    print(("  OK   " if cond else "  FALLA ") + nombre + ("" if cond else f"  {detalle}"))
    if not cond:
        fallas.append(nombre)

def neblina(alpha):
    # fraccion de pixeles semitransparentes LEJOS del solido (el "halo ancho")
    a = np.asarray(alpha).astype(np.float32)
    sol = (a >= 220).astype(np.uint8)
    if not sol.any():
        return 1.0
    lej = cv2.distanceTransform(1 - sol, cv2.DIST_L2, 3)
    return float(((a > 20) & (a < 220) & (lej > 3)).mean())

# alfa con HALO ancho semitransparente (lo que isnet/birefnet dejan y se ve como
# neblina sobre color): un cuadrado solido difuminado con un blur grande.
base = np.zeros((300, 300), np.float32)
base[100:200, 100:200] = 255.0
soft = cv2.GaussianBlur(base, (0, 0), 9.0)
soft_img = Image.fromarray(np.clip(soft, 0, 255).astype(np.uint8))

out = _alfa_apretado(soft_img)
o = np.asarray(out).astype(np.float32)

check("control: el halo de entrada SI tiene neblina", neblina(soft_img) > 0.05,
      f"{neblina(soft_img):.3f}")
check("aprieta: neblina ancha casi eliminada", neblina(out) < 0.01,
      f"{neblina(out):.3f}")
check("conserva el interior opaco", o[150, 150] >= 250, str(o[150, 150]))
check("el fondo lejano sigue transparente", o[10, 10] <= 5, str(o[10, 10]))

# SIN morfologia: una protuberancia fina pero OPACA no se borra (eso era lo que
# _alfa_fino se comia). Antena de 4px de ancho, alfa 255.
b2 = np.zeros((300, 300), np.float32)
b2[140:160, 140:160] = 255.0       # nucleo
b2[100:140, 148:152] = 255.0       # antena fina opaca
out2 = np.asarray(_alfa_apretado(Image.fromarray(b2.astype(np.uint8)))).astype(np.float32)
check("no se come una protuberancia fina OPACA", out2[110, 150] >= 250,
      str(out2[110, 150]))

if __name__ == "__main__":
    print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLA(S)'}")
    sys.exit(1 if fallas else 0)

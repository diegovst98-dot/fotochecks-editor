# Contrato del encuadre y del enderezado EXIF (sin modelo de IA, rapido).
#
# 1. caja_encuadre NUNCA debe pasar el borde INFERIOR de la foto: en fotos
#    que ya vienen recortadas tipo carnet la persona toca el borde de abajo
#    y no hay mas cuerpo; lo que falte saldria como franja blanca bajo el
#    torso (feedback disenadora 2026-07-01).
# 2. _abrir_enderezada endereza fotos de celular (orientacion EXIF) antes de
#    procesarlas: sin esto el modelo de IA recibe los pixeles de costado y
#    recorta una cara volteada (feedback disenadora 2026-07-01, caso Carlos).
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "codigo"))

from encuadre import caja_encuadre

fallas = []


def check(nombre, cond, det=""):
    if cond:
        print(f"  ok    {nombre}")
    else:
        print(f"  FALLA {nombre}  {det}")
        fallas.append(nombre)


# ---------- 1. la caja no pasa el borde inferior ----------
# Foto sintetica tipo carnet YA recortada: cabeza grande y torso que llega
# hasta el borde inferior (como las fotos base que mandan los clientes).
W, H = 240, 200
alpha = np.zeros((H, W), np.uint8)
yy, xx = np.mgrid[0:H, 0:W]
alpha[((xx - 120) ** 2 + (yy - 80) ** 2) < 55 ** 2] = 255   # cabeza (tope ~y=25)
alpha[150:H, 30:210] = 255                                   # torso hasta abajo
alpha_img = Image.fromarray(alpha)
img = Image.new("RGB", (W, H), (200, 200, 200))
cara = (78, 55, 84, 84)   # caja de la cara dentro de la cabeza

for nombre, preset in (
    ("carnet 3:4 cab 0.55", {"ancho_px": 900, "alto_px": 1200,
                             "cabeza_relativa": 0.55, "margen_superior": 0.05}),
    ("carnet 3:4 cab 0.68", {"ancho_px": 900, "alto_px": 1200,
                             "cabeza_relativa": 0.68, "margen_superior": 0.05}),
    ("casi cuadrado cab 0.68", {"ancho_px": 1067, "alto_px": 1031,
                                "cabeza_relativa": 0.68, "margen_superior": 0.05}),
):
    left, top, cw, ch = caja_encuadre(img, cara, alpha_img, preset)
    check(f"caja dentro de la foto por abajo ({nombre})",
          top + ch <= H, f"bottom={top + ch} vs alto={H}")
    check(f"caja con alto util ({nombre})", ch >= int(H * 0.5),
          f"ch={ch}")
    # el ancho sigue respetando el tope de la silueta (sin blanco a los lados)
    check(f"ancho no crece al achicar ({nombre})", cw <= int(180 * 0.94) + 1,
          f"cw={cw}")

# caso normal (foto con cuerpo de sobra): el tope NO debe activarse y la caja
# debe seguir saliendo con la formula historica (no cambiar fotos que ya
# salian bien).
H2 = 520
alpha2 = np.zeros((H2, W), np.uint8)
yy2, xx2 = np.mgrid[0:H2, 0:W]
alpha2[((xx2 - 120) ** 2 + (yy2 - 80) ** 2) < 55 ** 2] = 255
alpha2[150:H2, 30:210] = 255
img2 = Image.new("RGB", (W, H2), (200, 200, 200))
preset_n = {"ancho_px": 900, "alto_px": 1200,
            "cabeza_relativa": 0.55, "margen_superior": 0.05}
left, top, cw, ch = caja_encuadre(img2, cara, Image.fromarray(alpha2), preset_n)
# formula historica esperada (sin tope): ver caja_encuadre
ratio = 900 / 1200
alto_cabeza = max((55 + 84) - 25, 84)          # menton - tope del pelo
crop_h_cab = alto_cabeza / 0.55
crop_w_esp = min(crop_h_cab * ratio, (210 - 30) * 0.94)
crop_h_esp = crop_w_esp / ratio
check("caso normal: la formula historica no cambia",
      abs(ch - int(crop_h_esp)) <= 2 and abs(cw - int(crop_w_esp)) <= 2,
      f"esperado ~{int(crop_w_esp)}x{int(crop_h_esp)}, salio {cw}x{ch}")
check("caso normal: cabe por abajo", top + ch <= H2, f"bottom={top + ch}")

# ---------- 2. enderezado EXIF al abrir ----------
import editar_fotos as core

check("existe _abrir_enderezada en el pipeline",
      hasattr(core, "_abrir_enderezada"))
if hasattr(core, "_abrir_enderezada"):
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    base = Image.new("RGB", (60, 30), (0, 0, 255))
    for x in range(30):
        for y in range(15):
            base.putpixel((x, y), (255, 0, 0))   # cuadrante sup-izq ROJO

    # como la guarda un celular: pixeles girados + orientacion 6 en EXIF
    girada = base.transpose(Image.ROTATE_90)
    ex = Image.Exif()
    ex[274] = 6
    p6 = tmp / "cel_orient6.jpg"
    girada.save(p6, "JPEG", quality=95, exif=ex)
    im = core._abrir_enderezada(p6)
    check("orientacion 6: tamano enderezado", im.size == (60, 30), str(im.size))
    check("orientacion 6: contenido enderezado (rojo arriba-izq)",
          im.getpixel((5, 5))[0] > 180 and im.getpixel((55, 25))[2] > 180,
          f"{im.getpixel((5, 5))} / {im.getpixel((55, 25))}")

    # sin EXIF: no debe tocar nada
    p_plana = tmp / "sin_exif.jpg"
    base.save(p_plana, "JPEG", quality=95)
    im2 = core._abrir_enderezada(p_plana)
    check("sin EXIF: queda igual", im2.size == (60, 30), str(im2.size))

    # orientacion 8 (el otro giro tipico de celular)
    girada8 = base.transpose(Image.ROTATE_270)
    ex8 = Image.Exif()
    ex8[274] = 8
    p8 = tmp / "cel_orient8.jpg"
    girada8.save(p8, "JPEG", quality=95, exif=ex8)
    im3 = core._abrir_enderezada(p8)
    check("orientacion 8: tamano enderezado", im3.size == (60, 30), str(im3.size))

if fallas:
    print(f"{len(fallas)} falla(s): {fallas}")
sys.exit(1 if fallas else 0)

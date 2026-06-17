# Importar PDF: saca la(s) foto(s) de un PDF y las deja como PNG para que el
# editor las procese como una imagen normal. Por cada PAGINA: extrae la imagen
# incrustada mas GRANDE (pesca la foto, descarta logos/texto chicos); si la
# pagina no trae imagen aprovechable, RASTERIZA la hoja. Una foto por pagina.
# Via pypdfium2 (motor PDFium de Chrome; libre, autocontenida).
#
# El import va GUARDADO en try/except: si el .exe todavia no trae pypdfium2
# (build viejo), `DISPONIBLE` queda False y el resto del programa sigue
# funcionando -- el PDF queda "dormido" hasta que llegue el .exe reconstruido.
from pathlib import Path

try:
    import pypdfium2 as _pdfium
    import pypdfium2.raw as _praw
    DISPONIBLE = True
except Exception:
    _pdfium = None
    DISPONIBLE = False


def pdf_disponible():
    return DISPONIBLE


def _imagenes_grandes(page, min_lado):
    # Imagenes incrustadas de la pagina con lado menor >= min_lado px, de mayor
    # a menor area (la mayor suele ser la foto; los logos/iconos quedan fuera).
    res = []
    for obj in page.get_objects(filter=[_praw.FPDF_PAGEOBJ_IMAGE]):
        try:
            pil = obj.get_bitmap(render=True).to_pil().convert("RGB")
            if min(pil.size) >= min_lado:
                res.append(pil)
        except Exception:
            pass
    res.sort(key=lambda im: im.size[0] * im.size[1], reverse=True)
    return res


def pdf_a_imagenes(ruta_pdf, carpeta_dest, min_lado=300, dpi=200):
    # Devuelve la lista de PNG extraidos (1 por pagina). PDF dañado o sin
    # pypdfium2 -> lista vacia (el editor avisa y sigue sin romperse).
    if not DISPONIBLE:
        return []
    ruta_pdf = Path(ruta_pdf)
    carpeta_dest = Path(carpeta_dest)
    carpeta_dest.mkdir(parents=True, exist_ok=True)
    try:
        pdf = _pdfium.PdfDocument(str(ruta_pdf))
    except Exception:
        return []
    salidas = []
    try:
        n = len(pdf)
        for i in range(n):
            page = pdf[i]
            grandes = _imagenes_grandes(page, min_lado)
            if grandes:
                img = grandes[0]
            else:
                img = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
            # 1 pagina -> conserva el nombre (para el match con el Excel); varias
            # -> sufijo _pN (esas salen marcadas para nombrar a mano).
            stem = ruta_pdf.stem if n == 1 else f"{ruta_pdf.stem}_p{i+1}"
            destino = carpeta_dest / (stem + ".png")
            img.save(destino)
            salidas.append(destino)
    except Exception:
        pass
    finally:
        try:
            pdf.close()
        except Exception:
            pass
    return salidas

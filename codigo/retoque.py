# Retoque: color/brillo automaticos y la limpieza del borde del recorte.
# AQUI VIVE LA CALIBRACION GANADA A PULSO (2026-06-11, v10->v17): cada numero
# de este archivo se eligio probando contra fotos reales de clientes. Antes de
# cambiar cualquiera, leer la memoria del proyecto y correr los tests dorados.
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


# ---------- correcciones de color (automaticas por foto) ----------
# Como las fotos llegan de colores muy distintos (naranjas, rosadas...), un
# ajuste fijo no sirve: cada foto se MIDE y se corrige sola hacia un mismo
# objetivo. Asi un lote variado sale parejo sin tocar foto por foto.

def _factor_brillo_auto(img, preset):
    # Mide el brillo de la persona (ignora el fondo blanco) y calcula un factor
    # para llevar la mediana a un objetivo. Acotado para no quemar la foto.
    objetivo = preset.get("brillo_auto_objetivo", 180)
    rgb = np.array(img.convert("RGB"), dtype=np.int16)
    gris = np.array(img.convert("L"), dtype=np.float32)
    no_blanco = ~((rgb[:, :, 0] > 245) & (rgb[:, :, 1] > 245) & (rgb[:, :, 2] > 245))
    vals = gris[no_blanco]
    if vals.size < 100:
        return preset.get("brillo", 1.0)
    media = float(np.median(vals))
    if media <= 1:
        return preset.get("brillo", 1.0)
    return max(0.9, min(1.8, objetivo / media))


def _corregir_color(img, mask):
    # Neutraliza el tinte (balance de blancos tipo "mundo gris") usando solo los
    # pixeles de la persona, con limites para no matar el tono de piel. El fondo
    # blanco no se toca.
    arr = np.asarray(img).astype(np.float32)
    sel = arr[mask]
    if sel.shape[0] < 50:
        return img
    medias = sel.reshape(-1, 3).mean(axis=0)
    gris = float(medias.mean())
    ganancias = gris / np.clip(medias, 1.0, None)
    ganancias = np.clip(ganancias, 0.85, 1.18)
    corr = np.clip(arr * ganancias, 0, 255)
    arr2 = arr.copy()
    arr2[mask] = corr[mask]  # solo la persona; el fondo blanco queda intacto
    return Image.fromarray(arr2.astype(np.uint8))


def _corregir_saturacion(img, mask, objetivo):
    # Lleva la saturacion promedio de la persona hacia un objetivo (cada foto
    # sube o baja lo necesario). El blanco (saturacion 0) no se ve afectado.
    arr = np.asarray(img).astype(np.float32)
    sel = arr[mask].reshape(-1, 3)
    if sel.shape[0] < 50:
        return img
    mx = sel.max(axis=1)
    mn = sel.min(axis=1)
    s = np.where(mx > 0, (mx - mn) / np.clip(mx, 1, None), 0)
    media = float(s.mean())
    if media < 0.01:
        return img
    factor = float(np.clip(objetivo / media, 0.7, 1.4))
    return ImageEnhance.Color(img).enhance(factor)


def _subir_negros(img, piso):
    # Reduce la intensidad del negro: remapea [0..255] -> [piso..255], asi el
    # negro puro no imprime como "mancha" pesada en la Evolis. El blanco se queda
    # en blanco. Es una regla global (problema de la impresora, no de la foto).
    if not piso or piso <= 0:
        return img
    arr = np.asarray(img).astype(np.float32)
    arr = piso + arr * (255.0 - piso) / 255.0
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------- limpieza del borde del recorte ----------

def _limpiar_mascara(alpha, fuerza=1.0):
    # (Solo para el modelo CLASICO u2net, el de respaldo sin internet.)
    # Endurece la mascara del recorte para quitar el "cerco" o halo del fondo y
    # los pelos sueltos semitransparentes que sobre blanco se ven como un fleco
    # azulado/gris. Sube el contraste del canal alfa: lo intermedio (el halo) se
    # va a 0 (fondo) o a 255 (persona). 'fuerza' 0..1 = mas o menos agresivo.
    a = np.asarray(alpha).astype(np.float32) / 255.0
    # ventana de transicion: mas angosta = mas duro (corta mas halo y pelitos)
    centro = 0.55
    medio = 0.30 * (1.0 - 0.6 * fuerza)  # fuerza alta -> ventana mas angosta
    lo, hi = centro - medio, centro + medio
    a = np.clip((a - lo) / max(hi - lo, 1e-3), 0.0, 1.0)
    out = Image.fromarray((a * 255).astype(np.uint8))
    return out.filter(ImageFilter.MinFilter(3))  # recorta 1px de borde residual


def _alfa_fino(alpha, conservar_pelo=False):
    # Silueta "PEINADO ORDENADO" (decision de producto con Diego, 2026-06-11):
    # para un fotocheck no hace falta conservar cada pelo suelto; un contorno
    # limpio y ordenado se ve mejor y elimina de raiz los defectos de borde
    # (neblina, bolsones de fondo entre mechones, filos de color).
    # Pasos: 1) borde firme (smoothstep 110-160: fuera la neblina del modelo),
    # 2) apertura morfologica: retira mechones/frizz mas delgados que ~1% del
    #    lado menor de la foto (los huecos con color del fondo se van con
    #    ellos; aretes y monturas de lentes son mas gruesos y sobreviven),
    # 3) limpiar islas sueltas, 4) contorno suavizado con antialias de 1-2px.
    # conservar_pelo=True (salida en BLANCO, feedback Diego 2026-06-16): apertura
    # MUCHO menor -> respeta los mechones/rizos finos. El recorte firme (apertura
    # 0.5% + _recortar_cerco) solo hace falta sobre fondos de COLOR, donde el pelo
    # fino se ve como halo; sobre blanco no, y comerlo se ve peor.
    a = np.asarray(alpha).astype(np.float32)
    x = np.clip((a - 110.0) / (160.0 - 110.0), 0.0, 1.0)
    s = (x * x * (3.0 - 2.0 * x)) * 255.0
    binaria = (s > 127).astype(np.uint8)
    frac = 0.0015 if conservar_pelo else 0.005
    r = max(1 if conservar_pelo else 2, round(min(binaria.shape) * frac))
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    abierta = cv2.morphologyEx(binaria, cv2.MORPH_OPEN, nucleo)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(abierta, connectivity=8)
    if n > 1:
        area_max = stats[1:, cv2.CC_STAT_AREA].max()
        keep = [i for i in range(1, n)
                if stats[i, cv2.CC_STAT_AREA] >= max(200, area_max * 0.005)]
        abierta = np.isin(lab, keep).astype(np.uint8)
    suave = cv2.GaussianBlur(abierta.astype(np.float32), (0, 0), max(1.2, r * 0.45))
    # rampa corrida hacia adentro (~1px): recorta los pixeles mas externos del
    # contorno, que son los mas contaminados con el color del fondo original
    s = np.clip((suave - 0.45) / 0.20, 0.0, 1.0) * 255.0
    return Image.fromarray(s.astype(np.uint8))


def _recortar_cerco(img, alpha, cara=None):
    # El modelo a veces deja una FRANJA ANCHA del fondo original pegada al
    # contorno con alfa solido (tipico con paredes grises/beige y pelo difuso):
    # sobre una credencial de color se ve como un cerco palido alrededor de
    # toda la silueta (medido 2026-06-12 con f04/f06). La banda de borde de
    # _descontaminar (~4px) no alcanza: el cerco puede tener 10-15px.
    # Se empuja el borde hacia ADENTRO, 1px por pasada, solo mientras el pixel
    # del contorno siga pareciendo fondo original, con tope de ~2.5% del lado
    # menor para nunca comer cara ni hombros (si la piel se pareciera al
    # fondo, la distancia de color >35 la protege; el tope es el segundo
    # candado). Es la version guiada-por-color de la "rampa corrida hacia
    # adentro" de _alfa_fino, y solo RECORTA: nunca agrega silueta.
    img_np = np.asarray(img.convert("RGB"))
    a8 = np.asarray(alpha)
    fuera = a8 < 30
    if fuera.sum() < 500:
        return alpha
    # Fondo LOCAL, no global: las paredes reales traen gradiente y sombras
    # (la mediana global dejaba cerco en el lado sombreado, medido con f04).
    # blur(img*fuera)/blur(fuera) extiende el color del fondo hacia el borde.
    f32 = img_np.astype(np.float32)
    masc = fuera.astype(np.float32)
    sigma = max(8.0, min(a8.shape) * 0.02)
    masc_b = cv2.GaussianBlur(masc, (0, 0), sigma)
    fondo_local = np.zeros_like(f32)
    for c in range(3):
        fondo_local[..., c] = cv2.GaussianBlur(f32[..., c] * masc, (0, 0), sigma)
    valido = masc_b > 0.05
    fondo_local[valido] /= masc_b[valido, None]
    dif = np.abs(f32 - fondo_local).max(axis=2)
    parecido = (dif < 42) & valido
    sil = (a8 > 127).astype(np.uint8)
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    tope = max(4, round(min(a8.shape) * 0.025))
    ext = (sil == 0).astype(np.uint8)
    comio = False
    for _ in range(tope):
        borde = (cv2.dilate(ext, k3) == 1) & (sil == 1)
        comer = borde & parecido
        if not comer.any():
            break
        sil[comer] = 0
        ext = (sil == 0).astype(np.uint8)
        comio = True
    if comio:
        suave = cv2.GaussianBlur(sil.astype(np.float32), (0, 0), 1.0)
        # solo recortar: donde no se comio nada, el alfa original manda
        nuevo = np.minimum(np.clip(suave, 0.0, 1.0) * 255.0,
                           a8.astype(np.float32))
    else:
        nuevo = a8.astype(np.float32)
    # VELO: la franja SEMITRANSPARENTE con color de fondo (pelo desenfocado o
    # frizz sobre pared gris) la erosion no la toca porque no es solida; sobre
    # una credencial de color se ve como un aura palida (medido con f03/f08/
    # f10). Se atenua el alfa suave segun cuanto se parezca el pixel al fondo
    # local: puro fondo -> 0, mezcla real pelo+fondo (dif alta) -> intacto.
    soft = (nuevo > 0) & (nuevo < 250) & valido
    if soft.any():
        factor = np.clip((dif - 14.0) / (42.0 - 14.0), 0.0, 1.0)
        nuevo[soft] *= factor[soft]
    # NEBLINA ANCHA: semitransparencia lejos del nucleo solido (pelo
    # desenfocado / frizz contra la pared). La regla del proyecto: cualquier
    # zona semitransparente ANCHA se ve mal sobre fondos de color. El
    # antialias legitimo vive pegado al solido (1-2px); lo que flota mas
    # lejos con alfa intermedio es niebla y se apaga, sin importar su color.
    solido = (nuevo >= 220).astype(np.uint8)
    lejos = cv2.distanceTransform(1 - solido, cv2.DIST_L2, 3)
    paso = max(2.0, min(a8.shape) * 0.005)
    rampa = np.clip(2.0 - (lejos - paso) / paso, 0.0, 1.0)
    niebla = (nuevo > 0) & (nuevo < 220)
    nuevo[niebla] *= rampa[niebla]
    # BAHIAS DE CORONA: entrantes del fondo entre mechones despeinados del
    # contorno superior (medido con f08). Quedan selladas por un cuello de
    # antialias oscuro, asi que la erosion pixel a pixel nunca entra; aqui se
    # apagan por DISTANCIA geometrica al exterior, sin exigir camino. Solo por
    # ENCIMA de las cejas (cara y + 35% del alto de la cara): los aretes de
    # perla y las bisagras de lentes -- blancos legitimos pegados al contorno
    # -- viven de los ojos para abajo y no se tocan.
    cejas_y = (cara[1] + int(cara[3] * 0.35)) if cara is not None \
        else int(a8.shape[0] * 0.25)
    if cejas_y > 0:
        # dentro de una bahia rodeada de pelo el campo de fondo local no
        # llega (el blur no entra): alli manda la mediana global del fondo
        fondo_glob = np.median(f32[fuera].reshape(-1, 3), axis=0)
        fondo_b = np.where(valido[..., None], fondo_local, fondo_glob)
        dif_b = np.abs(f32 - fondo_b).max(axis=2)
        fuera_n = (nuevo < 30).astype(np.uint8)
        dist_fn = cv2.distanceTransform(1 - fuera_n, cv2.DIST_L2, 3)
        bahia = ((nuevo >= 30) & (dist_fn <= 32.0) & (dif_b < 42))
        bahia[max(cejas_y, 0):] = False
        if bahia.any():
            apagar = np.clip((dif_b - 14.0) / (42.0 - 14.0), 0.0, 1.0)
            nuevo[bahia] *= apagar[bahia]
    return Image.fromarray(nuevo.astype(np.uint8))


def _descontaminar(img, alpha, cara=None):
    # Limpia el COLOR del recorte sin tocar la forma. Dos males distintos
    # (medidos con fotos reales, 2026-06-11):
    #  1) BORDE: la franja del contorno trae la transicion pelo+fondo claro de
    #     la foto original (sobre cualquier fondo se ve como un filo palido).
    #     Se recolorea TODA la banda de borde (~4px + antialias) con el color
    #     del interior profundo mas cercano — nunca de pixeles que parezcan
    #     fondo (antes se tomaba de 2px adentro, donde la pintura sigue sucia).
    #  2) BOLSONES: manchas del fondo original atrapadas ENTRE rizos/mechones,
    #     opacas y encerradas (la apertura no las toca). Se recolorean SOLO si
    #     son manchas chicas: una prenda clara parecida al fondo es una region
    #     enorme y queda intacta (leccion de la v14: nunca borrarlas por alfa,
    #     que se come los brillos del pelo; recolorear es reversible a la vista).
    # 'cara' (opcional) = caja (x, y, w, h) EN COORDENADAS DE ESTE RECORTE:
    #     limita los bolsones a la zona de la cabeza (sobre el menton), para no
    #     confundir ropa clara (cuello de camiseta, saco beige) con huecos de
    #     peinado (medido 2026-06-12: las manchas de ropa caen bajo el menton).
    img_np = np.asarray(img.convert("RGB"))
    a8 = np.asarray(alpha)
    opaco = (a8 >= 200)
    fuera = (a8 < 30)
    if not opaco.any():
        return img.convert("RGB")
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    interior = cv2.erode(opaco.astype(np.uint8), k3, iterations=4).astype(bool)
    if not interior.any():
        interior = opaco

    parecido = None
    bolson = False
    if fuera.sum() >= 500:
        fondo_color = np.median(img_np[fuera].reshape(-1, 3), axis=0)
        dif = np.abs(img_np.astype(np.float32) - fondo_color).max(axis=2)
        parecido = dif < 35
        # Bolsones = huecos del peinado con el fondo original adentro. CUATRO
        # condiciones para no tocar jamas ropa clara ni brillos de la cara:
        # la mancha debe ser (1) CHICA, (2) estar CERCA del contorno exterior,
        # (3) tener un anillo alrededor claramente MAS OSCURO que ella (pelo;
        # antes se exigia pelo casi negro y los castanos/teñidos se escapaban,
        # medido 2026-06-12 con f04/f07) y (4) estar a la altura de la CABEZA
        # (sobre el menton): el cuello de una camiseta blanca o un saco beige
        # cumplen 1-3 pero viven debajo del menton.
        cand = ((a8 > 0) & parecido).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
        if n > 1:
            area_persona = max(int(opaco.sum()), 1)
            luma = img_np.astype(np.float32).mean(axis=2)
            dist_fuera = cv2.distanceTransform((~fuera).astype(np.uint8),
                                               cv2.DIST_L2, 3)
            # limite inferior de la zona "cabeza": el menton si hay cara
            # detectada; si no, el 60% del alto del recorte (aprox. hombros).
            if cara is not None:
                limite_y = cara[1] + cara[3]
            else:
                limite_y = int(a8.shape[0] * 0.60)
            sel = np.zeros(a8.shape, dtype=bool)
            alto, ancho = a8.shape
            for i in range(1, n):
                area = stats[i, cv2.CC_STAT_AREA]
                if not (4 <= area < max(80, area_persona * 0.02)):
                    continue
                x0 = stats[i, cv2.CC_STAT_LEFT]
                y0 = stats[i, cv2.CC_STAT_TOP]
                ww = stats[i, cv2.CC_STAT_WIDTH]
                hh = stats[i, cv2.CC_STAT_HEIGHT]
                if y0 + hh / 2 > limite_y:
                    continue  # bajo el menton: puede ser ropa, no se toca
                ys0, ys1 = max(0, y0 - 6), min(alto, y0 + hh + 6)
                xs0, xs1 = max(0, x0 - 6), min(ancho, x0 + ww + 6)
                comp = lab[ys0:ys1, xs0:xs1] == i
                if dist_fuera[ys0:ys1, xs0:xs1][comp].min() > 32:
                    continue  # lejos del borde: no es hueco de peinado
                anillo = cv2.dilate(comp.astype(np.uint8), k3,
                                    iterations=3).astype(bool) & ~comp
                if not anillo.any():
                    continue
                luma_rec = luma[ys0:ys1, xs0:xs1]
                if luma_rec[anillo].mean() <= luma_rec[comp].mean() - 18:
                    sel[ys0:ys1, xs0:xs1] |= comp
            if sel.any():
                bolson = sel

    reemplazar = ((a8 > 0) & ~interior)
    if bolson is not False:
        reemplazar = reemplazar | bolson

    fuente = interior & ~parecido if parecido is not None else interior
    if not fuente.any():
        fuente = interior
    fuente = fuente.astype(np.uint8)
    # distancia con etiquetas: para cada pixel, CUAL es su fuente mas cercana
    _d, labels = cv2.distanceTransformWithLabels(
        1 - fuente, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    coords = np.argwhere(fuente == 1)  # mismo orden (fila a fila) que labels
    mapped = np.clip(labels - 1, 0, len(coords) - 1)
    ys, xs = coords[:, 0], coords[:, 1]
    ext = img_np[ys[mapped], xs[mapped]]
    out = img_np.copy()
    out[reemplazar] = ext[reemplazar]
    return Image.fromarray(out)

# Editor de Fotos DISECOD — nucleo del procesamiento.
#
# Este archivo es el DIRECTOR DE ORQUESTA: une las piezas y expone todo lo que
# la interfaz (app.py) y los tests usan. Cada pieza vive en su propio modulo:
#
#   rutas.py          donde estan los archivos (base, config, preset, entrada)
#   motor_ia.py       el modelo de IA que separa persona/fondo + su descarga
#   excel_codigos.py  emparejar nombres de foto con el Excel del cliente
#   encuadre.py       detectar la cara y calcular el recorte
#   retoque.py        color/brillo automaticos y limpieza del borde (CALIBRADO)
#   firmas.py         firmas escaneadas -> tinta negra transparente
#   pedidos.py        revision de insumos, mensaje, hoja PDF, registro de lotes
#
# Compatibilidad: todos los nombres historicos siguen disponibles como
# editar_fotos.X (la interfaz hace `import editar_fotos as core` y los tests
# tambien); no cambiar las firmas publicas sin correr los tests dorados.
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

import firmas as _firmas
import pedidos as _pedidos
from rutas import (BASE, ENTRADA, CONFIG, EXTENSIONES, base_dir,
                   cargar_preset, pausar)
from motor_ia import (MODELO_FINO, MODELO_MAXIMO, new_session,
                      modelo_fino_descargado, modelo_maximo_descargado,
                      descargar_modelo_fino, sesion_recorte, sesion_maxima)
from excel_codigos import (_normalizar, _tokens, _es_codigo,
                           cargar_codigos, emparejar)
from encuadre import (ruta_cascade, detectar_cara, recortar_region,
                      recortar_alpha, top_cabeza, ancho_persona,
                      fila_hombros, caja_encuadre)
from retoque import (_factor_brillo_auto, _corregir_color, _corregir_saturacion,
                     _subir_negros, _limpiar_mascara, _alfa_fino, _descontaminar,
                     _recortar_cerco)
from pedidos import (_nitidez, revisar_fotos, mensaje_para_cliente,
                     hoja_aprobacion, recorte_dudoso)

# Carpeta de salida ACTIVA. La interfaz la reasigna (core.SALIDA = ...) cuando
# el usuario elige "Guardar en..."; por eso vive aqui y las funciones la leen
# al momento de guardar, no antes.
SALIDA = BASE / "salida"


def procesar_una(ruta, preset, session, nombre_salida=None, fino=False,
                 sin_fondo=None):
    # El pipeline completo de UNA foto: quitar fondo -> limpiar borde ->
    # encuadrar por la cara -> correcciones de color -> tamano final -> guardar.
    # 'sin_fondo' opcional: si ya se corrio el modelo afuera (para evaluar el
    # recorte), se reusa y NO se vuelve a correr; si es None, se calcula aqui
    # como siempre (asi las salidas no cambian: el candado de doradas sigue OK).
    from rembg import remove  # carga diferida (ya quedo cargado tras new_session)
    original = Image.open(ruta).convert("RGB")
    if sin_fondo is None:
        sin_fondo = remove(original, session=session)  # RGBA con transparencia

    # El fondo de salida decide cuanto pelo conservar: sobre BLANCO se respeta
    # el pelo fino; para TRANSPARENTE (credenciales de color) se usa el recorte
    # firme que evita el halo (feedback Diego 2026-06-16).
    fmt = preset["formato_salida"].upper()
    transparente = bool(preset.get("fondo_transparente")) and fmt == "PNG"
    if fino:
        # Modelo fino (isnet): borde firme + peinado ordenado (o conservando el
        # pelo si la salida es en blanco).
        alpha = _alfa_fino(sin_fondo.split()[-1], conservar_pelo=not transparente)
    else:
        # Modelo clasico (u2net): deja un cerco semitransparente (el fondo
        # original asomandose por el pelo fino) que sobre blanco se ve como un
        # halo azulado/gris con pelitos sueltos. Endurecer el alfa lo elimina.
        fuerza = float(preset.get("limpieza_pelo", 1.0))
        alpha = _limpiar_mascara(sin_fondo.split()[-1], fuerza)
    rgb_sin = sin_fondo.convert("RGB")
    sin_fondo = Image.merge("RGBA", (*rgb_sin.split(), alpha))

    fondo = Image.new("RGBA", sin_fondo.size, tuple(preset["color_fondo"]) + (255,))
    compuesta = Image.alpha_composite(fondo, sin_fondo).convert("RGB")

    cara = detectar_cara(compuesta)
    left, top, crop_w, crop_h = caja_encuadre(compuesta, cara, alpha, preset)
    encuadrada = recortar_region(compuesta, left, top, crop_w, crop_h, preset["color_fondo"])
    alpha_rec = recortar_alpha(alpha, left, top, crop_w, crop_h)
    mask = np.asarray(alpha_rec) > 50  # persona vs fondo en el recorte

    if fino:
        # Base de color limpia para AMBOS fondos (blanco y transparente): se
        # recorta el ORIGINAL (no la compuesta, que ya trae el blanco mezclado
        # en el borde) y se descontamina: el anillo del contorno toma el color
        # real del pelo. Recien despues, si el fondo es blanco, se compone.
        try:
            base = recortar_region(original, left, top, crop_w, crop_h,
                                   preset["color_fondo"])
            # la caja de la cara, llevada a coordenadas del recorte, acota
            # donde el retoque puede actuar (bahias de corona y bolsones)
            cara_rec = ((cara[0] - left, cara[1] - top, cara[2], cara[3])
                        if cara is not None else None)
            # El "recorte de cerco" (erosion del contorno) es lo que mas come
            # pelo: solo se necesita sobre fondos de COLOR, donde el cerco del
            # fondo se ve como halo. Sobre blanco se omite -> se respeta el pelo.
            if transparente:
                alpha_rec = _recortar_cerco(base, alpha_rec, cara_rec)
            limpia = _descontaminar(base, alpha_rec, cara_rec)
            if transparente:
                encuadrada = limpia
            else:
                lienzo = Image.new("RGBA", limpia.size,
                                   tuple(preset["color_fondo"]) + (255,))
                con_alfa = Image.merge("RGBA", (*limpia.split(), alpha_rec))
                encuadrada = Image.alpha_composite(lienzo, con_alfa).convert("RGB")
        except Exception:
            pass  # si algo fallara, queda la compuesta (como antes)

    # Correcciones de color (cada una se mide en esta foto y se corrige sola)
    if preset.get("color_auto"):
        encuadrada = _corregir_color(encuadrada, mask)
    if preset.get("saturacion_auto"):
        encuadrada = _corregir_saturacion(encuadrada, mask, preset.get("saturacion_objetivo", 0.40))
    encuadrada = _subir_negros(encuadrada, preset.get("piso_negro", 0))

    # Brillo (manual o automatico)
    if preset.get("brillo_auto"):
        factor = _factor_brillo_auto(encuadrada, preset)
    else:
        factor = preset.get("brillo", 1.0)
    if factor != 1.0:
        encuadrada = ImageEnhance.Brightness(encuadrada).enhance(factor)

    ancho_obj, alto_obj = preset["ancho_px"], preset["alto_px"]
    final = encuadrada.resize((ancho_obj, alto_obj), Image.LANCZOS)

    # Aviso de pixelado: si hubo que estirar mucho el recorte (la parte util de
    # la foto tenia pocos pixeles), la salida se vera borrosa.
    escala = max(ancho_obj / max(crop_w, 1), alto_obj / max(crop_h, 1))
    pixelado = escala > 1.8

    if transparente:
        a = alpha_rec.resize((ancho_obj, alto_obj), Image.LANCZOS)
        if not fino:
            # Con el modelo clasico el borde suave es fondo contaminado: se
            # binariza para que sobre fondos de color no se vea como halo. Con
            # el modelo fino NO: su borde suave es pelo real y se conserva.
            a = a.point(lambda v: 255 if v >= 128 else 0)
        final = Image.merge("RGBA", (*final.split(), a))

    ext = ".png" if fmt == "PNG" else ".jpg"
    stem = nombre_salida if nombre_salida else ruta.stem
    destino = SALIDA / (stem + ext)
    if fmt == "JPG" or fmt == "JPEG":
        final.save(destino, "JPEG", quality=95, dpi=(300, 300))
    else:
        final.save(destino, "PNG", dpi=(300, 300))
    return destino, cara is not None, pixelado


def evaluar_recorte(ruta, session_fino, session_clasica):
    # Corre el modelo fino (el que usa el pipeline) y, si hay un modelo clasico
    # distinto, mide el desacuerdo entre ambos para marcar recortes DUDOSOS
    # (ropa clara / pelo dificil que conviene rehacer en "Foto dificil").
    # Devuelve (sin_fondo_fino, dudoso): el sin_fondo se reusa en procesar_una
    # para no correr el modelo fino dos veces (solo se suma el clasico, ~1s).
    from rembg import remove
    original = Image.open(ruta).convert("RGB")
    sin_fondo = remove(original, session=session_fino)
    dudoso = False
    if session_clasica is not None:
        try:
            a_clas = remove(original, session=session_clasica).split()[-1]
            dudoso = recorte_dudoso(sin_fondo.split()[-1], a_clas)
        except Exception:
            dudoso = False
    return sin_fondo, dudoso


def procesar_firma(ruta, nombre_salida=None, color="negro"):
    # Guarda en la carpeta de salida ACTIVA (la que eligio el usuario).
    return _firmas.procesar(ruta, SALIDA, nombre_salida, color)


def registrar_lote(cliente, total, renombradas, carpeta):
    # BASE se lee al momento (los tests la redirigen para no ensuciar el real).
    _pedidos.escribir_lote(BASE / "lotes.csv", cliente, total, renombradas, carpeta)


def carpeta_pedido(cliente=""):
    # Carpeta del pedido de HOY para este cliente (pedidos/<fecha> <cliente>).
    return _pedidos.carpeta_pedido(BASE, cliente)


def recolectar_fotos():
    # Si se arrastraron fotos o carpetas encima del .exe, vienen como argumentos.
    # Si no, se usan las fotos de la carpeta 'entrada'.
    args = [Path(a) for a in sys.argv[1:]]
    fotos = []
    if args:
        for p in args:
            if p.is_dir():
                fotos += [q for q in sorted(p.iterdir())
                          if q.suffix.lower() in EXTENSIONES]
            elif p.suffix.lower() in EXTENSIONES and p.exists():
                fotos.append(p)
    elif ENTRADA.exists():
        fotos = [p for p in sorted(ENTRADA.iterdir())
                 if p.suffix.lower() in EXTENSIONES]
    return fotos


def main():
    preset = cargar_preset()
    fotos = recolectar_fotos()

    print("=" * 60)
    print(f"  Editor de fotos para fotochecks - DISECOD")
    print(f"  Preset: {preset['_nombre']}  ->  {preset['ancho_px']} x {preset['alto_px']} px")
    print(f"  Brillo: {preset['brillo']}   Fondo: {preset['color_fondo']}")
    print("=" * 60)

    if not fotos:
        print("\nNo hay fotos. Arrastra las fotos (o una carpeta) encima del programa,")
        print("o ponlas en la carpeta 'entrada' y vuelve a ejecutar.")
        pausar()
        return

    SALIDA.mkdir(parents=True, exist_ok=True)
    if modelo_fino_descargado():
        print(f"\nFotos a procesar: {len(fotos)}\nPreparando modelo de IA...\n")
    else:
        print(f"\nFotos a procesar: {len(fotos)}\nDescargando mejora del recorte"
              " de pelo (una sola vez, ~180 MB)...\n")
    session, fino = sesion_recorte(preset)

    inicio = time.time()
    ok = 0
    sin_cara = []
    errores = []
    for i, ruta in enumerate(fotos, 1):
        try:
            destino, hubo_cara, _pixelado = procesar_una(ruta, preset, session,
                                                         fino=fino)
            ok += 1
            marca = "" if hubo_cara else "  (!) sin cara detectada, recorte centrado"
            print(f"[{i}/{len(fotos)}] {ruta.name} -> {destino.name}{marca}")
            if not hubo_cara:
                sin_cara.append(ruta.name)
        except Exception as e:
            errores.append((ruta.name, str(e)))
            print(f"[{i}/{len(fotos)}] ERROR en {ruta.name}: {e}")

    seg = time.time() - inicio
    print("\n" + "=" * 60)
    print(f"  Listas: {ok}/{len(fotos)}  en {seg:.1f}s  ->  carpeta 'salida'")
    if sin_cara:
        print(f"  Revisar (sin cara detectada): {', '.join(sin_cara)}")
    if errores:
        print(f"  Con error: {', '.join(n for n, _ in errores)}")
    print("=" * 60)
    pausar()


if __name__ == "__main__":
    main()

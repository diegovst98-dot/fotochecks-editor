# Calado preciso para color — borde "apretado" (modelo fino)

> Diseño aprobado por Diego, 2026-06-18. Camino **B** (apretado en blanco y
> transparente). Toca `retoque.py` (archivo calibrado) y `editar_fotos.py`.
> Cambios SOLO de código → llegan por auto-update, NO se reconstruye el .exe.

## Problema (feedback de Mirza, 2026-06-18)

Mirza probó el editor con un lote real (fotos de empleados sobre backdrop **gris
claro**, no blanco puro). Reportó:

1. **El calado en PNG transparente no es preciso: bordes "muy difuminados".** Al
   poner la persona sobre un diseño de **color** (ej. credencial NIUBIZ) se ve un
   halo/neblina alrededor del pelo y la silueta.
2. Con **"mejorar foto difícil"** (BiRefNet) la *forma* sale mejor pero **demora
   mucho** (~1 min/foto, inviable para 200) y **el borde sigue difuminado** en PNG.
3. **El tinte/color YA mejoró** (neutro, no azulado). No se toca.
4. Para **fondo blanco** está conforme; el problema es el transparente para color.

Vara visual de Mirza: el calado del diseño NIUBIZ (pelo nítido sobre azul).

## Diagnóstico (medido, no a ojo — reglas del proyecto)

Pipeline actual del modelo fino: `isnet → _alfa_minimo → _descontaminar`.
`_alfa_minimo` solo **suaviza** el borde (gaussian = antialias). Ese borde suave:

- sobre **blanco** es invisible (blanco sobre blanco),
- sobre **color/transparente** se ve como **neblina** (la causa del "difuminado").

Medición sobre originales reales (76555499 y BERROCAL) + las 10 doradas,
compuesto sobre azul-NIUBIZ usando el alpha:

| Tratamiento del borde | neblina ancha (color) | dentado / pelo comido |
|---|---|---|
| `_alfa_minimo` (HOY) | ~0.6–2.1% (f1 frizz: 9.6%) | no, pero deja halo |
| **`apretado` (candidato)** | **~0.00–0.10% (f1: 2.8%)** | **no** (validado 10/10) |
| `_alfa_fino` (viejo, desactivado) | ~0% | **sí denta / come pelo** |

Hallazgos clave:
- El "difuminado" = borde suave exportado tal cual en transparente.
- **`apretado`** (contraste del alfa, **sin morfología**) borra el halo dejando el
  borde firme y preciso, **sin** dentar ni comer pelo (el dentado viejo venía de la
  *apertura morfológica* de `_alfa_fino`, que `apretado` no usa).
- **No hace falta BiRefNet**: apretado con isnet (~1 s) sale prácticamente igual que
  con BiRefNet (12–17 s). El techo lo da el post-proceso del borde, no el motor
  (consistente con el bake-off del proyecto).
- En **blanco** apretado no rompe nada (y recupera el borde firme "de antes" que
  Mirza extrañaba).

## Objetivo

Que el editor entregue bien las **dos** salidas que DISECOD realmente usa:
1. **Fondo blanco** para fotocheck (CardPresso).
2. **PNG transparente con calado preciso** para diseños de color.

Rápido (isnet), simple, sin sacrificar lo que ya funciona (tinte, encuadre,
renombrado, velocidad).

## Diseño

### 1. Nueva función `_alfa_apretado` en `retoque.py`
```
def _alfa_apretado(alpha, lo=100.0, hi=170.0, sigma=0.6):
    # Borde FIRME sin cirugía: aprieta el contraste del canal alfa (smoothstep
    # lo→hi: la neblina semitransparente se va a 0/255) + un antialias mínimo
    # (~1px). NO usa morfología (apertura/erosión) -> no denta ni come pelo, que
    # era el defecto de _alfa_fino. Reemplaza a _alfa_minimo para el modelo fino.
    a = np.asarray(alpha).astype(np.float32)
    x = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    s = (x * x * (3.0 - 2.0 * x)) * 255.0
    s = cv2.GaussianBlur(s, (0, 0), sigma)
    return Image.fromarray(np.clip(s, 0, 255).astype(np.uint8))
```
Parámetros 100/170/0.6 = los medidos (balance halo↔conservar pelo). Tunables.

### 2. Aplicarla en `editar_fotos.procesar_una` (rama `fino`)
Donde hoy hace `alpha = _alfa_minimo(sin_fondo.split()[-1])`, usar
`_alfa_apretado(...)`. El alpha se usa igual aguas abajo (encuadre, compose
blanco, export transparente), así que **afecta blanco y transparente** = camino B.
`_descontaminar` sigue corriendo igual (limpia el COLOR del borde).

### 3. Sin cambios
- Motor = **isnet** (rápido). NO se fuerza BiRefNet.
- Auto-mejora de "difíciles" (BiRefNet gated), "Foto difícil" manual: **igual**.
- Tinte/color/brillo/saturación: **igual** (ya bueno).
- Encuadre, renombrado, Excel, PDF, HEIC, pestañas, UI: **igual**.
- Funciones viejas (`_alfa_minimo`, `_alfa_fino`, `_recortar_cerco`): quedan en
  `retoque.py` **sin llamarse** (no se borran).

## Validación ya hecha (antes de implementar)
- 2 originales reales (incl. cola larga lacia) sobre azul y blanco: calado limpio.
- 10 fotos doradas sobre azul: neblina ~0 en todas, **sin dentado ni pelo comido**;
  rizado (f6/f8) y ropa clara (f4/f7) OK.
- isnet vs BiRefNet con apretado: equivalente → se descarta el motor lento.

## Candados / rollout (reglas del proyecto)
1. Las **20 doradas de foto del modelo fino** (10 blanco + 10 transp) **cambian a
   propósito** → regenerar con `python tests\correr_tests.py --aprobar` **SOLO tras
   revisar a ojo** las nuevas. Las **2 doradas de firma NO cambian** (no tocan el
   recorte). Nota: el encuadre puede correrse 1–2 px (el alfa cambia levemente la
   caja) — es esperado y las doradas lo capturan.
2. `python tests\correr_tests.py` debe quedar **verde** (incluye el audit de
   imports [1b]; no se agregan imports nuevos: `cv2`/`numpy`/`PIL` ya están).
3. **Confirmar con Diego antes de `python publicar.py`** (auto-update a Mirza y al
   vendedor). NO se reconstruye el .exe (solo código en `codigo/`).
4. Tras publicar: pedir a Mirza que pruebe un transparente sobre un diseño de color.

## Riesgos y perillas
- **Frizz extremo** (f1): apretado deja un resto mínimo de halo (2.8%). Subir la
  agresividad (lo/hi más juntos o más altos) empezaría a comer pelo → se dejó en el
  balance. Si Mirza pide más firme en un caso puntual, se ajusta el parámetro.
- Es un cambio en el **archivo calibrado**: el candado de doradas es la red de
  seguridad; revisar los diffs de doradas a ojo es obligatorio antes de `--aprobar`.

## Fuera de alcance (YAGNI)
- Armar/colocar la persona dentro de la plantilla de color (Diego lo descartó).
- Migrar de motor, reconstruir el .exe, tocar UI.
- Limpiar pelitos por separado en blanco más allá de lo que apretado ya hace.

## Artefactos de la medición
- Scripts: `Desktop\pruebas_calado\medir.py`, `medir2.py`, `medir10.py`.
- Montajes: `Desktop\pruebas_calado\*.png` (pares_A/B, *_navy, *_ZOOMBIG, *_blanco).

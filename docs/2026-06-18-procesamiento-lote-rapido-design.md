# Procesamiento del lote rápido + "mejorar las que elijas" (Fase 1)

> Diseño aprobado por Diego, 2026-06-18. Cambios SOLO de código (app.py) → llegan
> por auto-update, NO se reconstruye el .exe. La GPU (DirectML) es la **Fase 2**
> aparte (requiere rebuild) — este spec NO la incluye.

## Problema

Mirza procesó 252 fotos: en una PC muy buena tardó ~15 min; en su PC (i5-7400)
~1 hora. No puede pasar una hora procesando sin trabajar. Quiere todo en masa,
ordenado, **sin mover imágenes de carpeta en carpeta ni reprocesar todo**.

## Datos medidos (sobre las 252 reales, ver scripts en Desktop\pruebas_calado\)

- **isnet (el recorte):** 0.59 s/foto → 2.5 min las 252 (PC buena); ~6-8 min en la de Mirza.
- **Detector u2net (marca las difíciles):** +37% al tiempo. **Barato y confiable.**
- **Marcadas (dudosas): solo 18 de 252 (7%)**; 12-14 si se sube el umbral.
- **Casi todas las 18 marcadas se ven BIEN** con isnet+apretado (v36) → realmente
  malas son poquísimas. El detector es conservador (marca por desacuerdo de modelos).
- **El "aviso gratis" (fuzz del alfa) NO sirve**: solo coincide con 11/18 (61%).
- **El verdadero costo NO es el detector: es el BiRefNet automático inline**, que
  rehace ~18-20 fotos con el modelo lento (~1 min/foto en la PC de Mirza ≈ 20 min)
  **aunque casi todas ya estaban bien**. Ese es el desperdicio que bloquea a Mirza.

## Objetivo

Una sola pasada rápida; que el programa avise cuáles salieron a revisar; que Mirza
elija con un check las pocas que quiere rehacer con calidad alta (BiRefNet), y esas
se reemplacen **en la misma carpeta**; las no elegidas se quedan como salieron de
isnet. Simple, ordenado, sin mover carpetas, sin reprocesar todo.

## Diseño

### 1. Worker: solo isnet+apretado + MARCAR las dudosas (quitar el BiRefNet inline)
En `app.py` `worker()`, hoy: si una foto es `dudoso` y la auto-mejora está ON y
BiRefNet bajado → la rehace inline con BiRefNet (lento, bloquea). **Se elimina ese
bloque de auto-mejora inline** (las líneas del `if dudoso and auto_ok:`). Queda solo
el camino de **marcar**: la dudosa se anota en `resumen["dudoso"]` y su ruta en
`resumen["dudoso_rutas"]` (ya existe) y se marca en rojo en la galería. El detector
(`evaluar_recorte` = isnet + u2net) **se mantiene** (es barato y confiable).

### 2. Quitar la casilla "Mejorar las difíciles automáticamente"
Eliminar el checkbox `var_auto_mejora` (y `self.auto_mejora` en `iniciar`/`worker`).
Ya no hay auto-mejora inline; la mejora es post-lote y a elección.

### 3. Post-lote: diálogo de miniaturas con checkbox → reprocesar las elegidas en sitio
Al terminar el lote (manejo del mensaje `fin` en `revisar_cola`), si
`resumen["dudoso_rutas"]` trae fotos, abrir un **diálogo modal con miniaturas y un
checkbox por foto** (mismo estilo visual que `_resolver_confirmaciones`):
> "Estas N fotos salieron a revisar. Marca las que quieras rehacer con calidad alta
> (BiRefNet, más lento). Las que no marques quedan como están."
- Si marca ≥1 y acepta → se reprocesan **solo esas** con BiRefNet reusando el camino
  que YA existe: `iniciar(rutas_marcadas, maxima=True)`. Ese camino escribe en
  `core.SALIDA` con el mismo `nombre_salida` (código/DNI recalculado con
  `emparejar` + `self.resoluciones`) → **sobrescribe en la misma carpeta**, mismo
  nombre. Las no marcadas no se tocan (quedan como isnet).
- Si no marca nada / cierra → no pasa nada (todo queda como isnet).
- En modo `maxima` el worker NO corre el detector (`detectar_dudosos` ya es False con
  `modo_maximo`), así que el reproceso de las pocas es directo y sin doble modelo.

### 4. "Foto difícil" manual se queda
El botón `elegir_foto_dificil` (multi-select manual → `iniciar(maxima=True)`) se
mantiene como backstop para rehacer cualquier foto que el detector no haya marcado.

## Lo que NO cambia
- Motor isnet + `_alfa_apretado` (v36), tinte/color, encuadre, renombrado, Excel,
  PDF, HEIC, las 4 pestañas, "Revisar pedido", "Renombrar (CardPresso)".
- El detector (`evaluar_recorte`/`recorte_dudoso`) y su umbral (se puede afinar, opcional).
- No se reconstruye el .exe (solo código).

## Flujo de datos (en sitio, sin mover carpetas)
Entrada (fotos_dni) → isnet+apretado → `core.SALIDA` (carpeta del pedido). Las
elegidas en el diálogo → BiRefNet → **misma `core.SALIDA`, mismo nombre** (overwrite).
Una sola carpeta de salida de principio a fin.

## Candado / rollout
1. **Las doradas NO cambian** (este cambio es de flujo/UI en `app.py`, no toca el
   recorte ni `procesar_una`): el candado debe quedar verde sin regenerar doradas.
2. Actualizar el **humo de interfaz** del candado: hoy chequea cosas como
   `btn_dificil`, `_resolver_confirmaciones`, `var_resumen`. Quitar la referencia a
   `var_auto_mejora` (si la hubiera) y agregar un check del nuevo diálogo/función
   post-lote.
3. `python tests\correr_tests.py` verde. No se agregan imports nuevos al bundle.
4. **Confirmar con Diego antes de `publicar.py`** (auto-update a Mirza/vendedor).
5. Tras publicar: Mirza corre un lote real y confirma el tiempo + el flujo del diálogo.

## Riesgos y notas
- El reproceso en sitio sobrescribe archivos: si Mirza ya abrió uno en otro programa
  podría fallar el guardado → se maneja por-foto (un error no tumba el resto, ya hay
  try/except en el worker).
- Sobrescribir con el mismo `nombre_salida` depende de que el match (código) sea el
  mismo; como se reusa `emparejar` + `self.resoluciones`, es consistente.
- El detector se queda ON (barato). Si en su PC molesta el +37%, se puede agregar
  luego un toggle "saltar detección" (no en este spec — YAGNI).

## Fuera de alcance (YAGNI)
- **GPU/DirectML = Fase 2** (rebuild del .exe; spec aparte si la POC convence).
- Procesamiento en segundo plano (descartado: complejo y de más mantenimiento).
- "Aviso gratis" por fuzz (descartado: 61% de acierto, poco confiable).

## Métrica esperada
Lote de 252 en la PC de Mirza: de **~1 h** a **~10-15 min** (isnet+detector ~8-11 min
+ BiRefNet solo en las poquísimas que ella elija), una sola pasada, sin mover carpetas.

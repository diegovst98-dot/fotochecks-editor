# Matching tolerante a variaciones de nombres — Diseño

**Fecha:** 2026-06-17
**Proyecto:** Fotochecks Editor (`codigo/excel_codigos.py`, `codigo/pedidos.py`)
**Estado:** Diseño aprobado por Diego. Pendiente: plan de implementación (Fase 1).

## Problema

`emparejar()` hoy es deliberadamente conservador: solo cruza foto↔Excel cuando está
seguro (exacto / token-subset) y marca todo lo demás como `sin_match` o `ambiguo`.
En un pedido real (GFP, 252 fotos) esto generó 7 falsos "no figura en tu lista":

- **5 typos de una persona única** — variaciones obvias del mismo nombre:
  `Aroyo→Arroyo`, `Ossco→Oscco`, `Cristian→Cristhian`, `Giancarlos→Giancarlo`,
  `CarmenCondori→Carmen Condori`. El editor debería reconocerlas.
- **2 personas distintas con el mismo nombre** — los dos `Ricardo Flores` (DNI
  distintos). NO es un typo; el matching difuso no aplica, se necesita otra pista.

Riesgo central: poner un DNI equivocado en un fotocheck es grave. La tolerancia NO
puede convertirse en adivinar mal.

## Decisiones (acordadas)

1. **Híbrido** para typos: auto-empareja lo casi idéntico; propone Sí/No lo menos claro.
2. **Elegir a mano** para duplicados reales: mostrar candidatos (cargo + DNI), el
   operador elige.
3. **2 fases:** Fase 1 = algoritmo + tests (resuelve los 5 typos solo). Fase 2 = UI
   de confirmar/elegir en la pestaña "Revisar pedido".
4. **Sin dependencias nuevas:** librería estándar de Python → se publica con
   `publicar.py` y llega por auto-update, SIN reconstruir el `.exe`.

## Diseño del matching (las 3 bandas)

Para cada foto, se puntúa contra cada registro del Excel y se clasifica:

| Banda | Estado | Condición | Acción |
|---|---|---|---|
| 🟢 Auto | `aproximado` | candidato **único** casi idéntico **y** con margen claro sobre el 2º | empareja solo (como hoy con exactos) |
| 🟡 Sugerencia | `sugerencia` (nuevo) | un candidato bastante parecido, sin margen para auto | propone "¿Es X (DNI)?" → confirma operador |
| 🔴 Elegir | `ambiguo` | ≥2 candidatos parecidos (incl. nombres idénticos) | muestra candidatos, operador elige |
| ⚪ Nada | `sin_match` | ningún candidato razonable | se reporta como hoy |

### Regla de seguridad (no negociable)
Auto-emparejar SOLO si el mejor candidato gana por **margen** al segundo mejor. Si dos
personas compiten parejo → nunca auto; baja a 🟡/🔴. Esto impide fusionar dos personas
distintas con nombres parecidos.

### Cómo se mide la similitud (stdlib pura)
- **Por palabra:** distancia de edición (Levenshtein) pequeña (≤1–2 según largo) =
  misma palabra con typo. Cubre `aroyo/arroyo`, `ossco/oscco`, `cristian/cristhian`,
  `giancarlos/giancarlo`.
- **Sin espacios:** comparar la concatenación normalizada sin espacios. Cubre
  `carmencondori` = `carmen condori` (merge/split de tokens), y refuerza el resto.
- **Subconjunto de tokens:** se conserva la lógica actual (nombre recortado:
  `Hugo Morales Parra` → `Hugo Morales`).
- Implementación: Levenshtein en Python puro (sin imports nuevos). `difflib` queda
  como apoyo opcional (también es stdlib), pero el criterio de auto se basa en edit
  distance + margen, no en un ratio suelto.

Umbrales exactos se calibran con tests (abajo), usando los 5 typos reales como dorados.

## Cambios de código

- **`excel_codigos.py`**
  - Nueva función interna de similitud (Levenshtein puro + helpers sin-espacios).
  - `emparejar(stem, registros)` **mantiene su firma** `(codigo, estado)` para no
    romper llamadas existentes ni el candado (que hace `c, e = emparejar(...)`).
    Estados ampliados: agrega `sugerencia`; `ambiguo` ahora aplica también a typos que
    empatan. `aproximado` cubre los typos únicos con margen.
  - Nueva `emparejar_detalle(stem, registros)` que devuelve los **candidatos** (con
    codigo, nombre, cargo si existe, score) para que la UI muestre el Sí/No y el
    "elegir cuál". `emparejar()` se implementa encima de ésta.
- **`pedidos.py` → `revisar_fotos()`**: clasifica `sugerencia` y `ambiguo` con sus
  candidatos en la estructura de salida (no los mete en "sin_foto"/"no figura").
- **`pedidos.py` → `mensaje_para_cliente()`**: los casos resueltos por
  sugerencia/elección NO aparecen como "faltan/no figuran".

> Lectura de columnas: hoy `cargar_codigos` toma solo las 2 primeras columnas con
> datos. Para usar la pista de cargo (duplicados) y para Excels con columnas extra,
> conviene que detecte la columna de código (dígitos) y la de nombre aunque haya más
> columnas. Se evalúa como mejora incluida (afecta directamente el caso GFP de 6
> columnas). Si agranda el alcance, se separa a su propia fase.

## Alcance por fase

- **Fase 1 (esta):** similitud + bandas + `emparejar`/`emparejar_detalle` + tests.
  Resultado medible: los 5 typos reales pasan a `aproximado` (auto); los 2 Ricardo
  Flores quedan `ambiguo` con sus 2 candidatos. Sin cambios de UI todavía.
- **Fase 2 (después):** en "Revisar pedido", botones Sí/No (🟡) y selector de
  candidato (🔴); las decisiones alimentan renombrado y limpian el mensaje al cliente.

## Tests (candado)

Se mantienen los actuales y se agregan, en `tests/correr_tests.py` sección [2]:
- **Mantener:** `Maria Lopez` → `ambiguo` (2 Marías); `Pedro Inexistente` → `sin_match`;
  `ana torres` → `1004` aproximado; exacto sigue exacto.
- **Nuevos (positivos):** los 5 typos reales emparejan al DNI correcto en banda 🟢:
  `Cielo Aroyo→Arroyo`, `Estefania Ossco→Oscco`, `Cristian Camargo→Cristhian`,
  `Giancarlos Cuba→Giancarlo`, `Mary CarmenCondori→Mary Carmen Condori`.
- **Nuevo (negativo, seguridad):** dos personas distintas con nombres parecidos
  (p.ej. `Luis Garcia` y `Luis Gracia`) con una foto ambigua NO se auto-emparejan:
  debe caer en `sugerencia`/`ambiguo`, nunca auto a uno.
- **Nuevo:** un typo único que sí debe sugerir/auto, y verificar el margen vs 2º.

## Restricciones del proyecto (de las reglas fijas)

- **MEDIR, no adivinar:** calibrar umbrales corriendo sobre casos reales, no a ojo.
- **Candado verde antes de publicar** (`python tests\correr_tests.py`). Cambios al
  matching no tocan las doradas de imagen (corren aparte), pero sí la sección [2].
- **Sin imports nuevos** que no estén en el `.exe` → por eso stdlib pura; así NO se
  reconstruye el exe y llega por auto-update.
- **Publicar = `publicar.py`**, y confirmar con Diego antes (llega a Mirza/vendedor).

## Fuera de alcance (YAGNI)

- Auto-disambiguar duplicados por cargo "a la fuerza" (Diego eligió elegir a mano).
- Migrar a una librería de fuzzy matching externa (rapidfuzz, etc.): obligaría a
  reconstruir el exe; el beneficio no lo justifica para nombres cortos.
- Aprendizaje/memoria de correcciones previas entre pedidos.

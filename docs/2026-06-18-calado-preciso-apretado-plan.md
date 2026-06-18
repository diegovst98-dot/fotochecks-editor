# Calado preciso "apretado" — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el modelo fino exporte un borde firme y preciso (sin neblina) en blanco
y transparente, agregando `_alfa_apretado` y usándola en lugar de `_alfa_minimo`.

**Architecture:** Función nueva en `retoque.py` que aprieta el contraste del canal
alfa (smoothstep + antialias mínimo, SIN morfología → no denta ni come pelo). Se
enchufa en el único punto del pipeline donde el modelo fino calcula el alfa
(`editar_fotos.procesar_una`). Todo lo demás (motor isnet, tinte, encuadre,
renombrado, UI) queda igual.

**Tech Stack:** Python 3.12, numpy, OpenCV (cv2), Pillow. Runner de tests propio
del proyecto (`tests/correr_tests.py`, NO pytest). Las "doradas" (20 salidas de
foto comparadas pixel a pixel) son la red de seguridad del recorte.

**Nota de flujo (deliberada, distinta al "commit por tarea" genérico):** este repo
es el de distribución PÚBLICA; `git push` = auto-update a Mirza/vendedor. Por eso NO
se hace commit por tarea: se trabaja local, se pasa el candado, y al final —**con OK
explícito de Diego**— se corre `publicar.py` (hace version bump + commit + push). El
.exe NO se reconstruye (cambios solo de código en `codigo/`).

---

## File Structure

- **Modify** `codigo/retoque.py` — agregar `_alfa_apretado` (junto a `_alfa_minimo`).
- **Modify** `codigo/editar_fotos.py` — importar `_alfa_apretado` y usarla en
  `procesar_una` (rama `fino`) en vez de `_alfa_minimo`.
- **Create** `tests/test_alfa.py` — test rápido y autónomo (sin modelo) de la nueva
  función (estilo `tests/test_matching.py`).
- **Modify** `tests/correr_tests.py` — (a) correr `test_alfa.py` como parte del
  candado; (b) regenerar las doradas finas con `--aprobar` tras revisión visual.

---

### Task 1: Función `_alfa_apretado` (TDD con test rápido)

**Files:**
- Create: `tests/test_alfa.py`
- Modify: `codigo/retoque.py` (agregar función después de `_alfa_minimo`, ~línea 145)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_alfa.py` con este contenido exacto:

```python
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
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `cd C:\Users\Diego\fotochecks-editor && python tests\test_alfa.py`
Expected: FALLA con `ImportError: cannot import name '_alfa_apretado' from 'retoque'`
(la función todavía no existe).

- [ ] **Step 3: Implementar la función**

En `codigo/retoque.py`, **después** de `_alfa_minimo` (que termina en la línea ~145,
antes de `_recortar_cerco`), agregar:

```python
def _alfa_apretado(alpha, lo=100.0, hi=170.0, sigma=0.6):
    # Borde FIRME sin cirugia (2026-06-18, feedback Mirza: el calado en color salia
    # difuminado). Aprieta el contraste del canal alfa (smoothstep lo->hi: la
    # neblina semitransparente se va a 0 o 255) y deja un antialias minimo (~1px).
    # NO usa morfologia (apertura/erosion) -> a diferencia de _alfa_fino, no denta
    # ni se come el pelo. Reemplaza a _alfa_minimo para el modelo fino: da el borde
    # firme que se ve preciso sobre fondos de color y limpio sobre blanco.
    # Validado sobre las 10 fotos doradas + 2 originales reales (ver docs/
    # 2026-06-18-calado-preciso-apretado-design.md).
    a = np.asarray(alpha).astype(np.float32)
    x = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    s = (x * x * (3.0 - 2.0 * x)) * 255.0
    s = cv2.GaussianBlur(s, (0, 0), sigma)
    return Image.fromarray(np.clip(s, 0, 255).astype(np.uint8))
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `cd C:\Users\Diego\fotochecks-editor && python tests\test_alfa.py`
Expected: `TODO OK` (exit 0), las 5 líneas en OK.

---

### Task 2: Enchufar `_alfa_apretado` en el pipeline del modelo fino

**Files:**
- Modify: `codigo/editar_fotos.py:38-40` (import) y `codigo/editar_fotos.py:68-72`
  (rama `fino` de `procesar_una`)

- [ ] **Step 1: Agregar la función al import de retoque**

En `codigo/editar_fotos.py`, cambiar el bloque de import (líneas 38-40):

```python
from retoque import (_factor_brillo_auto, _corregir_color, _corregir_saturacion,
                     _subir_negros, _limpiar_mascara, _alfa_fino, _alfa_minimo,
                     _descontaminar, _recortar_cerco)
```

por:

```python
from retoque import (_factor_brillo_auto, _corregir_color, _corregir_saturacion,
                     _subir_negros, _limpiar_mascara, _alfa_fino, _alfa_minimo,
                     _alfa_apretado, _descontaminar, _recortar_cerco)
```

- [ ] **Step 2: Usar `_alfa_apretado` en la rama fino**

En `codigo/editar_fotos.py`, dentro de `procesar_una`, reemplazar el bloque
`if fino:` (líneas 68-72):

```python
    if fino:
        # Modelo fino (isnet/birefnet): POST-PROCESO MINIMO (solo suavizado del
        # borde). El matte del modelo ya es bueno; la cirugia pesada (apertura +
        # erosion de cerco) era la que mordia/dentaba el pelo (2026-06-16).
        alpha = _alfa_minimo(sin_fondo.split()[-1])
```

por:

```python
    if fino:
        # Modelo fino (isnet/birefnet): borde FIRME con _alfa_apretado (contraste
        # del alfa, SIN morfologia). El minimo (_alfa_minimo) dejaba un borde suave
        # que sobre color se veia como neblina ("difuminado", feedback Mirza
        # 2026-06-18); apretado lo elimina sin dentar ni comer pelo, y en blanco
        # queda limpio (validado en las 10 doradas). No re-agregar la cirugia
        # pesada (_alfa_fino/_recortar_cerco): esa era la que oscilaba v10->v27.
        alpha = _alfa_apretado(sin_fondo.split()[-1])
```

- [ ] **Step 3: El test rápido sigue verde**

Run: `cd C:\Users\Diego\fotochecks-editor && python tests\test_alfa.py`
Expected: `TODO OK`.

- [ ] **Step 4: Verificar que NO se rompió ningún import (compila)**

Run: `cd C:\Users\Diego\fotochecks-editor && python -c "import sys; sys.path.insert(0,'codigo'); import editar_fotos; print('import OK')"`
Expected: `import OK` (sin ImportError).

---

### Task 3: Enchufar `test_alfa.py` al candado

**Files:**
- Modify: `tests/correr_tests.py` (sección [1/6], después del bucle de compilación,
  ~línea 76 — antes del `if fallas: return`)

- [ ] **Step 1: Correr `test_alfa.py` como parte del candado**

En `tests/correr_tests.py`, justo **después** del bucle `for p in sorted((BASE /
"codigo").glob("*.py")): ...` de compilación (línea ~75) y **antes** de
`if fallas:  # sin compilacion no tiene sentido seguir` (línea 76), insertar:

```python
    # test rapido de _alfa_apretado (sin modelo): contrato del borde firme
    r = subprocess.run([sys.executable, str(AQUI / "test_alfa.py")],
                       capture_output=True)
    check("test_alfa (borde apretado)", r.returncode == 0,
          r.stdout.decode(errors="ignore")[-200:])
```

- [ ] **Step 2: Verificar que el candado corre el nuevo test (sin tocar doradas aún)**

Run: `cd C:\Users\Diego\fotochecks-editor && python tests\correr_tests.py`
Expected: aparece `OK    test_alfa (borde apretado)` en la sección [1/6]. Las
**doradas de foto FALLARÁN** (cambió el borde a propósito) — eso es esperado y se
resuelve en la Task 4. Las firmas y las unidades deben seguir en OK.

---

### Task 4: Revisar las doradas nuevas a ojo y aprobarlas

> Regla del proyecto: cambiar el recorte cambia las doradas finas; `--aprobar`
> SOLO tras revisar a ojo. Ya se validó apretado sobre estas mismas 10 fotos
> (montajes `Desktop\pruebas_calado\pares_A.png`/`pares_B.png`), pero acá se revisan
> las salidas REALES del pipeline completo (con encuadre + descontaminar + tamaño).

**Files:**
- Genera/actualiza: `tests/doradas/*_blanco.png` y `*_transp.png` (20 archivos).

- [ ] **Step 1: Generar las salidas nuevas a una carpeta de revisión (sin aprobar)**

Run:
```bash
cd C:\Users\Diego\fotochecks-editor && python -c "import sys; sys.path.insert(0,'codigo'); import shutil; from pathlib import Path; import editar_fotos as core; from PIL import Image; pre=core.cargar_preset(); pre.update({'formato_salida':'PNG','brillo':1.32,'brillo_auto':False,'piso_negro':0,'ancho_px':1067,'alto_px':1031,'color_auto':False,'saturacion_auto':False}); s,fino=core.sesion_recorte(pre); out=Path('tests/_revisar'); shutil.rmtree(out,ignore_errors=True); out.mkdir(parents=True); core.SALIDA=out; ent=sorted(p for p in Path('entrada').iterdir() if p.suffix.lower() in ('.jpg','.jpeg','.png')); [ (pre.__setitem__('fondo_transparente',t), core.procesar_una(f,pre,s,f.stem+('_transp' if t else '_blanco'),fino=fino)) for f in ent for t in (True,False)]; print('generadas en',out)"
```
Expected: `generadas en tests/_revisar` (20 PNG).

- [ ] **Step 2: Mirar las salidas nuevas (revisión humana)**

Abrir `tests/_revisar/` y revisar a ojo (especialmente los `_transp.png` sobre un
fondo de color, y el pelo rizado f6/f8 y ropa clara f4/f7): el borde debe verse
**firme y sin neblina**, sin dentado ni pelo comido. **Diego/Claude confirman** que
se ven bien antes de aprobar. (Si algo se ve mal en una foto puntual, ajustar
`lo/hi/sigma` en `_alfa_apretado` y volver a la Task 1.)

- [ ] **Step 3: Aprobar las doradas**

Run: `cd C:\Users\Diego\fotochecks-editor && python tests\correr_tests.py --aprobar`
Expected: `APROBADAS N salidas doradas...` y al final `RESULTADO: TODO OK`.

- [ ] **Step 4: Candado completo en verde (confirmación final)**

Run: `cd C:\Users\Diego\fotochecks-editor && python tests\correr_tests.py`
Expected: `RESULTADO: TODO OK` (0 fallas). Limpiar la carpeta de revisión:
`rm -rf tests/_revisar`.

---

### Task 5: Publicar (CHECKPOINT — requiere OK explícito de Diego)

> `publicar.py` corre el candado, sube versión, hace commit y **push** → auto-update
> a Mirza y al vendedor al abrir. NO reconstruye el .exe (solo código).

- [ ] **Step 1: Confirmar con Diego**

Mostrar a Diego el resultado del candado verde + (si quiere) un par de salidas
`_transp` sobre color. **Esperar su "publica".** Sin ese OK, NO continuar.

- [ ] **Step 2: Publicar**

Run: `cd C:\Users\Diego\fotochecks-editor && python publicar.py`
Expected: corre el candado (verde), sube la versión, commit + push OK.

- [ ] **Step 3: Avisar a Mirza**

Pedirle que cierre y reabra el editor (baja la versión nueva sola) y que pruebe un
transparente sobre un diseño de color para confirmar el calado.

---

## Self-Review (hecho)

- **Cobertura del spec:** función nueva (Task 1) ✓; usada en blanco+transp = camino B
  (Task 2) ✓; isnet/tinte/UI sin tocar ✓; candado + doradas + confirmar antes de
  publicar (Tasks 3-5) ✓; funciones viejas quedan sin llamar ✓.
- **Sin placeholders:** todo el código y los comandos están completos.
- **Consistencia de nombres:** `_alfa_apretado(alpha, lo=100.0, hi=170.0, sigma=0.6)`
  idéntica en spec, test, implementación e import. `procesar_una`, `cargar_preset`,
  `sesion_recorte`, `SALIDA`, `fondo_transparente` = nombres reales del código.
- **Riesgo controlado:** no se agregan imports nuevos al bundle (cv2/numpy/PIL ya
  están — el audit [1b] no se dispara); las firmas no cambian; publicar va con OK.

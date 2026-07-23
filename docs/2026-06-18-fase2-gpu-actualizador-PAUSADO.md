# Fase 2 — GPU (DirectML) + actualizador de motor — PAUSADO (2026-06-18)

> Estado: **EN PAUSA por decisión de Diego.** Se midió y se decidió NO desplegar
> todavía. Este doc guarda TODO lo necesario para retomarlo sin re-investigar.
> Motivo de la pausa: el GPU da solo **2× end-to-end** (no 12×) y la Fase 1 ya
> bajó el lote de ~1 h a ~10-13 min; el costo/riesgo de repartir un .exe de 1.8 GB
> + construir el actualizador de motor no se justifica hasta que Mirza pruebe Fase 1.

## Specs de la PC de Mirza (la diseñadora)
- CPU: **Intel i5-7400** @3.0 GHz (4 núcleos, 2017) — el cuello real.
- RAM: 16 GB. GPU: **AMD Radeon RX 580 8 GB** (DX12 ✓). Win 10 Pro.

## Hallazgo medido (POC en la PC de Diego, RTX 4070 Ti)
- **CUDA = NO** (es solo NVIDIA; la de Mirza es AMD). **DirectML = SÍ** (AMD/NVIDIA/
  Intel vía DX12). ROCm = solo Linux. → **DirectML es el único camino para su RX 580.**
- Inferencia pura: isnet **12×** en GPU (45 ms vs 547 ms), BiRefNet **2×** (6.2 s vs 12.4 s).
- **Pipeline COMPLETO (procesar_una, lo que importa): GPU = 2.0× end-to-end**
  (383 vs 766 ms/foto). El recorte es solo la mitad del trabajo; encuadre +
  descontaminar + resize + guardar son CPU y no los toca la GPU. 252 fotos: CPU
  ~3.2 min, GPU ~1.6 min (en la PC de Diego; en la de Mirza ambos más lentos).
- En la PC de Diego el .exe DirectML **abre limpio** y usa `DmlExecutionProvider`
  (confirmado en registro.log + el benchmark).

## Cómo retomar (cuando se decida)

### 2a-A — Código de selección de GPU (REVERTIDO del source, va acá)
En `codigo/motor_ia.py`, reemplazar el `new_session` simple por esto (no-op seguro
en bundles de solo-CPU; usa GPU si el bundle trae onnxruntime-directml):
```python
def _mejores_providers():
    try:
        import onnxruntime as ort
        disp = set(ort.get_available_providers())
    except Exception:
        return None
    pref = []
    if "DmlExecutionProvider" in disp:
        pref.append("DmlExecutionProvider")
    if "CUDAExecutionProvider" in disp:
        pref.append("CUDAExecutionProvider")
    pref.append("CPUExecutionProvider")
    return pref


def new_session(*args, **kwargs):
    from rembg import new_session as _new_session
    if "providers" not in kwargs:
        prov = _mejores_providers()
        if prov:
            kwargs["providers"] = prov
    return _new_session(*args, **kwargs)
```
(El candado queda verde con esto: en dev/CPU elige `CPUExecutionProvider`, doradas
no cambian. Se REVIRTIÓ del source el 2026-06-18 para dejar el source = v37
publicado = lo que corre todo el mundo, sin malentendidos.)

### 2a-B — Rebuild del .exe con DirectML
`collect_all('onnxruntime')` del `.spec` ya empaca lo que esté instalado → basta
instalar onnxruntime-directml en el build env. Pasos (el `.exe` debe estar cerrado;
build a `dist_full` aparte para no tocar el editor en uso):
```bash
cd /c/Users/Diego/fotochecks-editor
python -m pip uninstall -y onnxruntime onnxruntime-directml
python -m pip install onnxruntime-directml
rm -rf dist_full build
python -m PyInstaller --noconfirm --distpath dist_full FotochecksEditor.spec
cp -r modelo dist_full/FotochecksEditor/ ; cp config.json dist_full/FotochecksEditor/ ; cp -r codigo dist_full/FotochecksEditor/
# RESTAURAR dev a CPU (para que el candado siga en CPU y las doradas no cambien):
python -m pip uninstall -y onnxruntime-directml ; python -m pip install onnxruntime
```
Verificado: `DirectML.dll` (18.5 MB) queda en `_internal/onnxruntime/capi/`. El
bundle pesa ~1.8 GB (con modelo). Probar SIEMPRE lanzando el .exe (no a ciegas).
Ojo PC multi-GPU: DirectML usa el device 0 por defecto; si elige mal, fijar
`device_id` en los providers.

### 2b — Actualizador de motor (la pieza delicada, NO empezada)
Para que los cambios de .exe/librería/modelo también lleguen solos: el launcher
revisa una "versión de bundle", baja las piezas nuevas (de **GitHub Releases**, que
aguanta archivos grandes), las deja en staging y un mini-arranque las cambia AL
REABRIR (un .exe en uso no se sobreescribe en caliente) con verificación de
integridad + rollback. Riesgo alto (un update de motor mal aplicado puede dejar el
editor sin abrir) → merece su propio spec + pruebas antes de tocarlo.

## Alternativa sin GPU (a evaluar si Fase 1 no basta)
Paralelizar el trabajo de CPU: procesar varias fotos a la vez en los 4 núcleos de
la i5-7400 (mientras la IA corre una, la CPU encuadra/guarda otra). Podría dar
más que el 2× del GPU **sin repartir binarios ni el actualizador de motor**.

## Condición para retomar
Que Mirza pruebe la Fase 1 (v37) en su PC y, si AÚN siente lento el lote, recién ahí
decidir entre: (a) desplegar GPU (2a-B + 2b), o (b) paralelizar CPU.

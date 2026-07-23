# Continuidad — Editor de Fotos DISECOD

> Para quien tenga que mantener esto si Diego no está (o para Diego dentro de seis
> meses). No explica cómo USAR el editor — eso es `GUIA-DE-USO.md`. Explica cómo
> publicar cambios, cómo deshacerlos y cómo reconstruir todo desde cero.

## Qué es, en una línea

App de escritorio (Python + Tkinter, empaquetada con PyInstaller) que edita fotos de
empleados en lote para fotochecks. La usa **Mirza (diseñadora)**; el vendedor usa la
pestaña "Revisar pedido". Corre 100% local, sin internet salvo para actualizarse.

## Dónde vive cada cosa

| Cosa | Dónde | ¿Se recupera solo? |
|---|---|---|
| Código fuente | GitHub `diegovst98-dot/fotochecks-editor` (público) | Sí — `git clone` |
| Proyecto de trabajo | `C:\Users\Diego\fotochecks-editor\` | — |
| Doradas del candado (22) | NO en GitHub. Backup semanal → `fotochecks-editor\doradas\` | Sí — del zip de backup |
| `config.json` / `lotes.csv` | NO en GitHub (data). Backup semanal | Sí — del zip de backup |
| Modelo de IA (1.3 GB) | `modelo\` — no se respalda | Sí — se vuelve a bajar (rembg `isnet-general-use`) |
| `.exe` armado + `_internal` | `dist\FotochecksEditor\` — no se respalda | Sí — se reconstruye con PyInstaller |

El backup corre solo **los lunes 1:30pm** (tarea de Windows "DISECOD Backup Semanal"),
guarda en `C:\Users\Diego\backups\` y copia a **OneDrive → Backups-DISECOD**.

## Cómo llega un cambio a la PC de Mirza

El `.exe` es un **launcher delgado**: al abrir, mira `manifest.json` en GitHub y, si la
versión es mayor a la suya, baja la carpeta `codigo\` (unos KB) y arranca con eso.
**Por eso el repo es público:** el launcher descarga sin credenciales. Meterle un token
sería peor (un token dentro de un .exe repartido es un token filtrado).

Consecuencia práctica: **cambios de código llegan solos**; cambios de librería o de
modelo **no** — esos necesitan repartir el .exe.

## Publicar un cambio

```bash
python publicar.py
```

Hace, en orden: corre el candado de tests → si falla, **no publica nada** → sube el
número de versión → arma `manifest.json` → `git push`. Las PCs se actualizan al abrir.

Antes de publicar, **confirmarlo con Diego**: llega a todas las PCs del equipo.

## El candado (lo más importante de entender)

`tests\correr_tests.py` procesa fotos de referencia y compara el resultado contra las
**22 salidas doradas** ya aprobadas. Si una salida cambia, no deja publicar.

Si el cambio es intencional y ya se revisaron las nuevas salidas **a ojo**:

```bash
python tests\correr_tests.py --aprobar
```

⚠️ **Las doradas no están en GitHub.** Si se pierden, el candado no falla: simplemente
deja de proteger, en silencio. Se restauran del zip de backup a `tests\doradas\`.

## Deshacer una versión que salió mal

**No** editar `codigo\version.txt` hacia atrás: el launcher solo actualiza cuando la
versión de GitHub es **mayor**, así que bajar el número no llega a nadie. Lo correcto es
revertir el contenido y publicar una versión **nueva**:

```bash
git revert --no-edit <hash-del-commit-malo>
python publicar.py
```

Sale una versión más alta con el código viejo, y esa sí baja sola a todas las PCs.

## Si a alguien no le llega la actualización

1. Que **cierre y reabra** el editor (solo actualiza al arrancar).
2. Revisar `actualizacion.log` en la carpeta del programa.
3. Causa típica: sin internet, o el antivirus bloqueó la descarga.

## Reconstruir el .exe (solo si cambió una librería o el modelo)

Un import nuevo en `codigo\` **tiene que existir dentro del bundle** o el editor
crashea en la PC de Mirza aunque funcione acá (pasó con `logging.handlers` y con
`ImageDraw`). El candado audita esto, pero solo parcialmente.

Se construye con `FotochecksEditor.spec`, a un `distpath` aparte (`dist_full\`) porque
el editor suele estar abierto y bloquea sus archivos. **Regla de Diego: cada vez que se
reconstruye el .exe, se rearma el ZIP COMPLETO** (exe + `_internal` + `modelo` + `codigo`
+ `config.json`, **sin** `pedidos\`, `salida\`, `lotes.csv`, `*.log`, `ultimo.json`) y se
deja en la carpeta del proyecto para repartir.

## Instalar en una PC nueva

Copiar la carpeta entera `dist\FotochecksEditor` (~1.7 GB) o el ZIP COMPLETO. **Extraer
con "Extraer todo"** (no ejecutar el .exe desde dentro del zip) a una carpeta simple en
`C:\` — **no** en Escritorio ni OneDrive: OneDrive deshidrata el `python312.dll` y sale
el error "Failed to load Python DLL". Para acceso fácil, **acceso directo**, nunca copiar
el .exe suelto (necesita `_internal` al lado). La primera carga del modo IA tarda.

Antes de dársela a un tercero, borrar la data: `pedidos\`, `lotes.csv`, `*.log`,
`ultimo.json`.

## Lo que NO se toca sin leer antes

El recorte de fondo (`codigo\retoque.py`, funciones `_alfa_*`) está calibrado tras una
saga larga de versiones. Hay reglas fijas escritas en
`C:\Users\Diego\claude-cerebro\fotochecks-editor.md` — **leerlas antes de tocar nada de
recorte**. Resumen: nada de morfología, y si un recorte sale mal el problema casi siempre
es la foto de origen, no el algoritmo.

## Si hay que recuperar todo desde cero

1. `git clone https://github.com/diegovst98-dot/fotochecks-editor.git`
2. `pip install -r requirements.txt`
3. Restaurar `tests\doradas\` + `config.json` del último zip de backup (OneDrive →
   Backups-DISECOD).
4. El modelo se baja solo la primera vez que se procesa una foto.
5. `python tests\correr_tests.py` — si da verde, el entorno quedó bien.

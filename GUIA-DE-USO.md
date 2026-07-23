# Editor de Fotos Fotochecks — DISECOD
## Guía de uso (versión 16)

> El programa se actualiza solo cada vez que se abre (necesita internet).
> La versión aparece arriba, en el título de la ventana. Si alguien reporta un
> problema, lo primero es preguntar: **"¿qué versión dice el título?"**

---

## Las 3 pestañas

| Pestaña | Para qué sirve | Quién la usa |
|---|---|---|
| **Procesar fotos** | Convertir las fotos del cliente en fotos de fotocheck listas (fondo, tamaño, brillo, renombrado al código) | Diseñadora |
| **Revisar pedido** | Revisar lo que mandó el cliente ANTES de producir y armar el mensaje para pedirle lo que falta | Vendedor (o quien reciba el pedido) |
| **Firmas** | Convertir firmas escaneadas/fotografiadas en tinta negra con fondo transparente | Diseñadora |

---

## El flujo completo de un pedido (recomendado)

1. **Llega el pedido por WhatsApp** (fotos + Excel del personal).
2. **Vendedor → pestaña "Revisar pedido"** (toma 1 minuto):
   - Paso 1: elegir las fotos que mandó el cliente (o la carpeta donde las guardaste).
   - Paso 2: elegir el Excel del personal (opcional pero recomendado).
   - Paso 3: botón **REVISAR PEDIDO**.
   - El programa detecta: personas del Excel **sin foto**, fotos **borrosas** o
     muy chicas, fotos que **no cruzan** con la lista, y repetidas.
   - Abajo aparece **el mensaje listo para el cliente**. Se puede editar.
     Botón **"Copiar mensaje para WhatsApp"** → pegar en el chat con Ctrl+V.
   - Si dice **TODO CONFORME**, el pedido pasa a producción de una.
   - 💡 Hacer esto APENAS llega el pedido evita descubrir problemas a mitad de
     la producción y perder días en idas y vueltas.
3. **Diseñadora → pestaña "Procesar fotos"**:
   - **Cliente:** si es un cliente recurrente, elegirlo en la lista de arriba —
     se aplica sola su configuración (medida, fondo, acercamiento, etc.).
     La primera vez: configurar todo a mano y pulsar **"Guardar cliente"**.
   - **Dónde se guarda:** solo, en la carpeta del pedido — `pedidos\fecha + cliente`
     (junto al programa). Ahí quedan juntas las fotos, firmas y la hoja de
     aprobación de ese trabajo. El programa abre la carpeta al terminar.
     **"Guardar en..."** es solo para casos especiales (otra carpeta); si lo
     usas después de procesar, el programa ofrece copiar lo ya hecho.
   - **"Elegir Excel de codigos"**: para que las fotos salgan renombradas con
     el código del empleado (lo que CardPresso necesita). Las dudosas salen
     con su nombre original y marcadas en ROJO para revisarlas a mano.
   - **"Elegir fotos"** (o "Elegir una carpeta") → el programa procesa todo.
   - ⏳ La PRIMERA vez en una PC descarga una mejora del recorte (~180 MB,
     una sola vez). Dejarlo terminar.
4. **Botón "Hoja de aprobacion (PDF)"** (se activa al terminar el lote):
   genera un PDF con todas las fotos y sus códigos para que **el cliente
   apruebe ANTES de imprimir**. Se manda por WhatsApp y se espera el
   "APROBADO". Esto evita reimpresiones por nombres o códigos mal puestos.
5. **Imprimir en CardPresso** con las fotos ya renombradas.

---

## Pestaña "Procesar fotos" — referencia rápida

- **Tamaño de salida:** en píxeles (el programa recuerda el último usado).
- **Brillo:** manual (calibrado para la Evolis) o "automatico" (se ajusta foto
  por foto).
- **Formato:** PNG (más calidad / permite transparente) o JPG (más liviano).
- **Fondo:** Blanco o Transparente (para montar sobre diseños de color).
- **Color:** correcciones opcionales (tinte, saturación, reducir negros).
- **Acercamiento:** más cuerpo ↔ rostro grande.
- Las fotos con **borde rojo "revisar"** en la galería: sin cara detectada,
  nombre no encontrado en el Excel, o salieron pixeladas. Revisarlas a mano.
- **"Foto difícil"**: si UNA foto sale con el pelo imperfecto, este botón la
  reprocesa con el modelo de IA más potente. Tarda bastante más que el modo
  normal (hasta ~1 minuto por foto — es normal, no está colgado), por eso se
  usa solo para casos puntuales, no para el lote completo. La primera vez
  descarga el modelo (~900 MB, una sola vez).
- Si el resumen final dice **"Se uso el recorte CLASICO"**: no hubo internet
  para descargar la mejora de pelo. Revisar la conexión y volver a procesar.

## Pestaña "Firmas" — referencia rápida

- Sirve cualquier firma con **tinta oscura sobre papel claro** (escaneada o
  foto de celular, aunque tenga sombra).
- Salen en PNG con tinta negra pura, fondo transparente, recortadas al trazo,
  con el nombre original + `_firma`.

---

## Para Diego: el archivo `lotes.csv`

Cada lote procesado queda registrado en **`lotes.csv`** (junto al programa, en
la PC que procesó): fecha, cliente, cuántas fotos, cuántas renombradas y a qué
carpeta se guardó. Se abre con Excel.

**Revisarlo 1 vez al mes:** dice qué cliente imprimió, cuánto y cuándo →
es la lista de a quién llamar para renovaciones y personal nuevo (alimenta la
mecánica de recompra en Kommo). Para que el registro diga el nombre del
cliente, la diseñadora debe elegir el **Cliente** antes de procesar.

---

## Problemas comunes

| Síntoma | Causa / solución |
|---|---|
| Salió el aviso "Ups, algo falló" | El reporte técnico **ya quedó copiado**: abre el chat de soporte y pégalo con Ctrl+V. Puedes seguir usando el programa. (También queda guardado en `registro.log`, junto al programa.) |
| La primera vez se queda "descargando mejora (~180 MB)" | Es normal, UNA sola vez por PC. Dejarlo terminar. |
| Resumen dice "recorte CLASICO" | Sin internet en ese momento. Conectar y reprocesar. |
| ¿Dónde quedaron mis fotos? | En `pedidos\fecha + cliente` (junto al programa); la barra verde muestra la ruta exacta y la carpeta se abre sola al terminar. Si elegiste "Guardar en...", están donde elegiste. |
| Una foto salió con borde raro | Mandar esa foto específica al chat de soporte (se calibra y se publica mejora en minutos). |
| ¿Qué versión tengo? | Está en el título de la ventana (ej. "v16"). Se actualiza sola al abrir. |

*Guía generada el 11/06/2026 — corresponde a la versión 16.*

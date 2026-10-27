# Contrato de la API de BioVigIA — v1

**Estado:** congelado el 27/10/2026 · **Responsable:** Tommy Guevara (BVIA-30)
**Base:** `/api/v1` · **Zona horaria del proyecto:** `America/Guayaquil` (−05:00)

Este documento es el acuerdo entre el **servicio de visión** (Francisco) y el **servidor**
(Darlyn). Mientras se respete, los dos pueden trabajar en paralelo sin hablarse. Si algo
tiene que cambiar, se avisa en el grupo **antes** de cambiarlo: no se modifica este archivo
sin que los cinco lo sepan.

---

## 1. Las seis reglas que no se negocian

1. **El servidor manda sobre el veredicto.** El servicio de visión envía el recipiente de
   destino; el servidor recalcula el veredicto a partir de él (`rojo` → `conforme`,
   `comun` → `no_conforme`) y **no se fía** del que llega. Si no coinciden, el servidor
   guarda el suyo y deja la discrepancia en el log.
2. **`id_externo` es único y lo genera la visión.** Si llega repetido, el servidor
   responde `200` con el evento que ya existe en lugar de crear otro. Esto es lo que
   permite que la cola del borde reintente sin duplicar (RNF-12).
3. **Las fechas van en ISO 8601 con zona horaria.** `2026-10-27T10:42:18.331-05:00`.
   Nunca se usa la hora del servidor para fechar el evento: el evento ocurrió donde está
   la cámara.
4. **La evidencia es el recorte del recipiente, nunca el fotograma completo** (RNF-03).
   Es opcional: si falta, el evento se registra igual.
5. **Un tramo sin observar se devuelve como `null`, jamás como `0`** (RNF-06). Cero
   eventos y "no estábamos mirando" son cosas distintas y el tablero las dibuja distinto.
6. **El rol lo decide el servidor a partir de la sesión**, nunca el cliente. Ninguna
   petición lleva el rol como parámetro.

---

## 2. Autenticación

| Quién | Cómo |
|---|---|
| Servicio de visión | `Authorization: Token <token-del-servicio>`. Un token fijo por dispositivo de borde, creado desde el panel de administración de Django. |
| Navegador | Sesión de Django (cookie). Las rutas de consulta exigen sesión iniciada. |

Errores de autenticación: `401` si no hay credencial o es inválida; `403` si la hay pero
el rol no alcanza para esa ruta.

---

## 3. `POST /api/v1/eventos` — ingesta de un descarte

Es el único mensaje que entra al sistema desde fuera. Todo lo demás es consulta.

### Petición

```json
{
  "id_externo": "box2-20261027T104218.331-05:00",
  "box": "box-2",
  "recipiente": "comun",
  "veredicto": "no_conforme",
  "confianza": 0.91,
  "ocurrido_en": "2026-10-27T10:42:18.331-05:00",
  "modelo": "biovigia-gasa-v0.1",
  "rasgos": {
    "fotogramas_confirmacion": 3,
    "duracion_s": 1.5,
    "confianza_media": 0.88,
    "area_media_px": 1340
  },
  "evidencia_jpeg_b64": "/9j/4AAQSkZJRgABAQAAAQ..."
}
```

| Campo | Tipo | Obligatorio | Reglas |
|---|---|---|---|
| `id_externo` | texto, ≤ 80 | sí | Único. Formato sugerido: `<box>-<marca de tiempo ISO sin separadores>`. |
| `box` | texto, ≤ 20 | sí | Identificador del puesto. En el MVP siempre `box-2`. |
| `recipiente` | enum | sí | `rojo` \| `comun` |
| `veredicto` | enum | sí | `conforme` \| `no_conforme`. El servidor lo recalcula igual. |
| `confianza` | decimal | sí | Entre 0 y 1, tres decimales. |
| `ocurrido_en` | ISO 8601 | sí | Con zona horaria. No puede ser futuro. |
| `modelo` | texto, ≤ 40 | sí | Nombre y versión de los pesos que lo generaron. |
| `rasgos` | objeto | sí | Se guarda tal cual. Puede crecer: el servidor no valida sus claves. |
| `evidencia_jpeg_b64` | texto | no | JPEG en base64 del recorte del recipiente. Máximo 2 MB. |

### Respuestas

**`201 Created`** — evento nuevo:

```json
{
  "id": 412,
  "id_externo": "box2-20261027T104218.331-05:00",
  "veredicto": "no_conforme",
  "recipiente": "comun",
  "estado_recipiente": "contaminado",
  "evidencia_guardada": true
}
```

**`200 OK`** — ya existía ese `id_externo`. Mismo cuerpo, con `"duplicado": true`.
El servicio de visión lo trata como éxito y borra el evento de su cola.

**`422 Unprocessable Entity`** — el cuerpo no cumple el contrato:

```json
{ "error": "validacion", "campo": "confianza", "detalle": "debe estar entre 0 y 1" }
```

**`401`** sin token válido. El evento **se queda en la cola** y se reintenta.

### Qué hace el servidor al recibirlo

1. Valida el cuerpo.
2. Busca `id_externo`; si existe, devuelve `200` y no toca nada más.
3. Recalcula el veredicto desde `recipiente`.
4. Guarda el evento y, si vino, la evidencia como archivo.
5. Si el veredicto es `no_conforme` y el recipiente estaba `normal`: lo pasa a
   `contaminado`, anota `contaminado_desde` y escribe una fila en `cambio_estado`.
6. Devuelve el estado del recipiente **después** del evento.

### Prueba rápida

```bash
curl -X POST http://localhost:8000/api/v1/eventos \
  -H "Authorization: Token $TOKEN_VISION" \
  -H "Content-Type: application/json" \
  -d '{"id_externo":"prueba-001","box":"box-2","recipiente":"comun",
       "veredicto":"no_conforme","confianza":0.91,
       "ocurrido_en":"2026-10-27T10:42:18.331-05:00","modelo":"prueba","rasgos":{}}'
```

Repetir el mismo comando debe devolver `200` con `"duplicado": true` y **no** crear un
segundo evento. Esa es la prueba de BVIA-37 y de BVIA-44.

---

## 4. `GET /api/v1/tablero` — PAN-02

Parámetros: `fecha` (`AAAA-MM-DD`, por defecto hoy) y `turno` (`manana` \| `tarde`).

```json
{
  "fecha": "2026-10-27",
  "turno": "manana",
  "actualizado_en": "2026-10-27T10:45:00-05:00",
  "kpis": {
    "descartes": 128,
    "no_conformes": 9,
    "cumplimiento": 0.930,
    "recipientes_contaminados": 1,
    "periodos_no_observados": 1
  },
  "por_hora": [
    { "hora": "07:00", "total": 28, "no_conformes": 2, "estado": "observado" },
    { "hora": "09:00", "total": null, "no_conformes": null, "estado": "sin_observar",
      "detalle": "Cámara desconectada de 09:04 a 09:21" },
    { "hora": "11:00", "total": null, "no_conformes": null, "estado": "pendiente" }
  ],
  "recipientes": [
    { "box": "box-2", "tipo": "rojo",  "estado": "normal" },
    { "box": "box-2", "tipo": "comun", "estado": "contaminado",
      "contaminado_desde": "2026-10-27T10:42:18-05:00" }
  ]
}
```

Los tres valores de `estado` en `por_hora` son `observado`, `sin_observar` y `pendiente`,
y en los dos últimos `total` va en `null`. El tablero dibuja trama gris para
`sin_observar` y nada para `pendiente`.

---

## 5. `GET /api/v1/eventos` y `/api/v1/eventos/{id}` — PAN-03 y PAN-04

Lista con `desde`, `hasta`, `turno`, `recipiente`, `veredicto`, `pagina` (8 por página).

```json
{ "total": 128, "pagina": 1, "paginas": 16, "items": [ { "...": "..." } ] }
```

Detalle:

```json
{
  "id": 412,
  "ocurrido_en": "2026-10-27T10:42:18-05:00",
  "turno": "manana",
  "box": "box-2",
  "recipiente": "comun",
  "veredicto": "no_conforme",
  "confianza": 0.91,
  "modelo": "biovigia-gasa-v0.1",
  "rasgos": { "fotogramas_confirmacion": 3, "duracion_s": 1.5 },
  "evidencia": { "disponible": true, "url": "/media/evidencia/412.jpg" },
  "estado_recipiente_tras_evento": "contaminado"
}
```

Cuando la evidencia venció por retención (RNF-17): `{"disponible": false, "motivo": "retencion"}`.
El evento **se conserva** con su veredicto; solo desaparece la imagen.

---

## 6. `GET /api/v1/recipientes` — PAN-05

```json
{
  "actualizado_en": "2026-10-27T10:45:00-05:00",
  "items": [
    { "box": "box-2", "tipo": "comun", "estado": "contaminado",
      "contaminado_desde": "2026-10-27T10:42:18-05:00", "evento_causa_id": 412 }
  ],
  "cambios_hoy": [
    { "hora": "10:42", "de": "normal", "a": "contaminado", "evento_id": 412 },
    { "hora": "08:15", "de": "contaminado", "a": "normal", "recambio_id": 77 }
  ]
}
```

`evento_id` solo se devuelve a los roles `supervisor` y `admin`: el personal de limpieza
no accede a los eventos.

---

## 7. `POST /api/v1/recambios` — PAN-06

```json
{ "box": "box-2", "tipo": "comun" }
```

**`201 Created`**

```json
{ "id": 78, "estado": "normal", "registrado_en": "2026-10-27T10:51:03-05:00" }
```

**`409 Conflict`** — el recipiente no estaba contaminado:

```json
{ "error": "no_contaminado",
  "detalle": "El recipiente ya está en estado normal; no hace falta registrar el recambio." }
```

Es la única regla de negocio no trivial del MVP y viene del criterio 3 de HU-03. El
frontend muestra el aviso informativo, no un error rojo.

---

## 8. Modelo de datos del MVP

Cinco tablas. Ni una más hasta que el MVP pase la prueba de aceptación.

| Tabla | Campos |
|---|---|
| `recipiente` | `id`, `box`, `tipo` (rojo/comun), `estado` (normal/contaminado), `contaminado_desde` |
| `evento` | `id`, `id_externo` (único), `recipiente_id`, `veredicto`, `confianza`, `ocurrido_en`, `turno`, `modelo`, `rasgos` (JSON), `evidencia` (ruta) |
| `recambio` | `id`, `recipiente_id`, `registrado_por`, `registrado_en`, `evento_causa_id` |
| `cambio_estado` | `id`, `recipiente_id`, `estado_anterior`, `estado_nuevo`, `ocurrido_en`, `evento_id`, `recambio_id` |
| `usuario` | el de Django + `rol` (`admin` / `supervisor` / `operativo`) |

`turno` se calcula al guardar a partir de `ocurrido_en`. **Pendiente de confirmar con el
cliente los horarios reales**; mientras tanto: mañana 07:00–12:59, tarde 13:00–18:59.

---

## 9. Cómo se cambia este contrato

1. Quien necesita el cambio lo propone en el grupo, con el motivo.
2. Si nadie se opone en un día, se aplica y se anota abajo.
3. Un campo **nuevo y opcional** no rompe nada y puede añadirse sin ceremonia.
4. Quitar un campo, renombrarlo o cambiar un valor de enumeración **sí rompe**: eso sube
   la versión a `/api/v2` y no se hace durante el MVP.

### Registro de cambios

| Fecha | Cambio | Quién |
|---|---|---|
| 27/10/2026 | Versión 1, congelada. | Tommy |

# Propuesta: detección en dos etapas (mano → gasa)

**Estado: etapa 1 (disparador) implementada en la rama `vision/deteccion-dos-etapas`,
pendiente de revisión por Francisco y Ezequiel. Etapa 2 (recorte) sin empezar.**
**Autor: Tommy Guevara · 10/11/2026 · Parte de la rama `integracion/mvp`**

## El problema

La gasa es pequeña. `vision/captura.py` normaliza cada fotograma a **640 × 480** antes de
pasarlo al detector, y a 60–80 cm la gasa queda en unas pocas decenas de píxeles. Buscarla
en la imagen completa, en todos los fotogramas, da dos fallos previsibles: descartes que
no se detectan y detecciones de «gasa» donde solo hay un brillo o un reflejo blanco.

La canalización actual es:

```
captura (M1) → detección de gasa en todo el fotograma (M2) → reglas k-de-N (M3) → evento (M4)
```

Las reglas de M3 ya filtran bien la gasa que roza la boca y se retira. Lo que esta
propuesta ataca es el paso anterior: que M2 vea la gasa, y que no la invente.

## La idea

No buscar la gasa todo el tiempo. Buscarla **solo cuando una mano se acerca a los
recipientes**, y solo en la parte de la imagen donde puede estar.

| Etapa | Qué hace | Por qué es más fácil |
|---|---|---|
| **1. Disparador** | Detecta una **mano o antebrazo** cerca de las zonas de los recipientes. | La mano es un objeto grande y se ve bien con el encuadre actual. |
| **2. Gasa** | Mientras el disparador está activo, busca la gasa en un **recorte** alrededor de la mano y de la boca del recipiente, tomado de la imagen original, antes de reducirla. | En el recorte la gasa ocupa una proporción mucho mayor de la imagen. |
| **3. Reglas** | Sin cambios: `MotorConfirmacion` y la regla k-de-N deciden el veredicto. | No cambia. |

Sin mano cerca, ninguna gasa llega a M3: no puede haber evento. Eso baja los eventos
falsos (RNF-07).

### Recorrido de un descarte

1. Reposo: no hay mano. Las detecciones de gasa se ignoran.
2. Una mano entra en el **área de aproximación** (las zonas de los recipientes ampliadas
   con un margen) → el disparador se activa.
3. La gasa se detecta en el recorte y sus cajas se devuelven a coordenadas del fotograma
   de 640 × 480, de modo que el seguimiento y las reglas no notan la diferencia.
4. La mano sale. El disparador sigue activo un tiempo de gracia, al menos la ventana de
   confirmación (1,5 s), para que M3 pueda confirmar por desaparición o por permanencia.
5. M3 emite el evento. La evidencia sigue siendo el recorte del recipiente (RNF-03).

## Qué está hecho: el disparador (etapa 1)

No es un filtro que tira detecciones: es una **cuarta condición en las reglas de M3**. Una
trayectoria de gasa solo puede confirmarse si **apareció junto a una mano**: hubo una mano
en el área de aproximación como mucho `gracia_mano_s` (2 s) antes o después de que la
gasa se viera por primera vez.

Se hizo así, y no descartando las gasas cuando no hay mano, porque el motor necesita
seguir viendo lo que ya está dentro del recipiente. Una trayectoria que nace sin mano —un
reflejo, un papel que ya estaba— se marca como residual y entra en la memoria de «ya
contado», de modo que tampoco genera evento si reaparece cuando una mano la tapa un
momento.

| Archivo | Cambio |
|---|---|
| `vision/tipos.py` | Clase opcional `MANO = "mano"`. |
| `vision/deteccion.py` | Alias (`mano`, `antebrazo`, `brazo`). Cada detector declara `detecta_mano`. El detector de desarrollo puede aproximar la mano por color de piel en movimiento, solo si se pide. |
| `vision/disparador.py` (nuevo) | `DisparadorMano.evaluar`: ¿hay una mano tocando el área de aproximación? |
| `vision/reglas.py` | `MotorConfirmacion.exige_mano`, el tiempo de gracia y los rasgos `mano_detectada` y `confianza_mano`. |
| `vision/pipeline.py` | Crea el disparador según la configuración y lo consulta en cada fotograma. La vista previa dibuja la mano y muestra `mano: SI/no`. |
| `vision/configuracion.py` | `BIOVIGIA_DISPARADOR` (`auto`, `si`, `no`), `BIOVIGIA_GRACIA_MANO_S`, `BIOVIGIA_MARGEN_MANO` y la opción `--disparador`. |
| `herramientas/evaluar_reglas.py` | Opción `--disparador` para comparar con y sin él. |
| `vision/tests/test_disparador.py` (nuevo) | 17 pruebas. |

**Por defecto no cambia nada.** En modo `auto` el disparador solo se activa si el modelo
cargado tiene la clase `mano`. Con un modelo de tres clases, o con el detector de
desarrollo, todo funciona como antes.

### Medición con los 20 videos del 10/11/2026

Detector de desarrollo (`--detector movimiento`) y zonas provisionales trazadas a ojo
(`datos/zonas.provisional.json`, para pasar con `--zonas`). No
son las cifras del informe: sirven para comparar el antes y el después.

| | Sin disparador | Con disparador (`--disparador si`) | Meta |
|---|---|---|---|
| Exactitud de asignación (RNF-08) | 11/16 = 69 % | 12/16 = 75 % | ≥ 90 % |
| Eventos falsos (RNF-07) | 55 % | 45 % | ≤ 5 % |

Mejoró lo que se esperaba: el evento falso de `vacio_02`, donde no hay ninguna mano, y un
duplicado en `rojo_06`. No mejoró lo que ocurre **mientras la mano está en escena**: los
eventos falsos en el recipiente común durante un descarte al rojo, los duplicados y los
dos clips `negativo_`. Eso depende de la calidad del detector de gasa, no del disparador,
y es lo que deben resolver el modelo entrenado y la etapa 2.

## Qué falta: la búsqueda en recorte (etapa 2)

- `vision/captura.py`: conservar la imagen original en `Fotograma`, antes de reducirla.
- `vision/pipeline.py`: con la mano activa, pasar al detector un recorte a resolución
  completa alrededor de la mano y la boca del recipiente, y devolver las cajas a
  coordenadas de 640 × 480.

## Qué cambia para cada uno

| Quién | Cambio |
|---|---|
| **Tommy** (escena) | Los clips deben mostrar la mano y el antebrazo **entrando al cuadro**. Ver `docs/escena-montaje.md`. |
| **Ezequiel** (datos) | Se anotan **cuatro clases**: `gasa`, `recipiente_rojo`, `recipiente_comun` y `mano`. |
| **Francisco** (visión) | Revisar la etapa 1 y decidir si se hace la etapa 2. |
| **Darlyn y Cristofer** | Nada. El contrato de la API no cambia. |

## El contrato no se toca

El campo `rasgos` es libre: el servidor lo guarda tal cual y no valida sus claves. Las
claves nuevas son opcionales:

```json
"rasgos": {
  "fotogramas_confirmacion": 3,
  "duracion_s": 1.5,
  "confianza_media": 0.88,
  "area_media_px": 1340,
  "mano_detectada": true,
  "confianza_mano": 0.93
}
```

Ojo con `ReglaConClasificador`: su lista `COLUMNAS` es fija. Las claves nuevas no la
rompen, pero el clasificador no las usará hasta que se reentrene con ellas.

## Postura del brazo: después del MVP

La idea original era reconocer al paciente por el **brazo flexionado** tras la punción y
empezar a capturar cuando se acerca a los recipientes. Se deja para después por tres
razones:

- **La cámara actual no ve el brazo.** Apunta a las bocas de los recipientes; solo
  entran la mano y parte del antebrazo. Medir la flexión exige ver hombro, codo y
  muñeca, es decir, una **segunda cámara** de plano abierto.
- **La flexión no coincide con el descarte.** El paciente camina con el brazo flexionado,
  pero al botar la gasa lo extiende o usa la otra mano. Sirve para saber que viene un
  paciente recién puncionado, no para decidir el veredicto.
- **Privacidad.** Un plano abierto capta personas completas. Habría que procesar solo
  los puntos de la pose y no guardar esas imágenes (RNF-03).

Cuando se retome no hace falta entrenar un modelo: los modelos de pose de `ultralytics`
(ya en `requirements-vision.txt`) entregan hombro, codo y muñeca, y el ángulo del codo
se calcula con esos tres puntos. Iría en `rasgos` como `angulo_codo_grados`.

Para no tener que volver a montar la escena, se graban desde ya unos clips de plano
abierto (ver `docs/escena-montaje.md`, sección 2).

## Pendiente de decidir en equipo

- [ ] ¿Se adopta el diseño en dos etapas? ¿Se fusiona la etapa 1?
- [ ] ¿La clase `mano` va en el mismo modelo o en uno aparte?
- [ ] Valores de `margen_mano` (hoy 1,0) y `gracia_mano_s` (hoy 2 s) con el modelo real.
- [ ] Crear la tarjeta en Jira para este cambio.

# Montaje de la escena y grabación de los videos base

**Tarea BVIA-32 · Responsable: Tommy Guevara · Día 2 (28/10/2026)**

Sin acceso todavía al laboratorio, replicamos la estación de descarte en un montaje
propio. Lo que se grabe aquí es lo único con lo que el modelo va a aprender, así que
media hora de cuidado en el montaje ahorra dos días de reentrenamiento.

---

## 1. El montaje

| Elemento | Cómo |
|---|---|
| **Recipientes** | Dos: uno **rojo** y uno **negro u oscuro**. Sirven dos baldes, dos tachos pequeños o dos cajas forradas. Lo que importa es que se distingan por color y que las bocas sean visibles. |
| **Separación** | Entre 30 y 40 cm, uno al lado del otro. Si están muy juntos, los polígonos se tocan y la regla de confirmación se vuelve ambigua. |
| **Cámara** | A 60–80 cm, **desde arriba y en diagonal**, de modo que se vea el interior de las dos bocas. No de frente: de frente no se ve dónde cae la gasa. |
| **Fijación** | Trípode, o una pila de libros con cinta. **La cámara no se puede mover** entre la grabación y las pruebas: si se mueve, los polígonos que trace Francisco dejan de servir y hay que volver a empezar. |
| **Fondo** | Claro y liso. Una pared, una cartulina, un mantel. Sin estampados. |
| **Luz** | La de la habitación. Evitar luz directa que haga brillo dentro de los recipientes, y evitar grabar con el sol entrando por una ventana a la espalda. |
| **La gasa** | Gasa o algodón blanco. Si tienes varias, mejor: unas más arrugadas, otras más abiertas. |

**Antes de grabar nada:** marca con cinta en el piso o la mesa dónde van la cámara y los
dos recipientes. Si algo se mueve, lo devuelves a su sitio sin discutir.

---

## 2. Los 20 videos

Clips de **10 segundos a 30 fps**. Graba video, no fotos: 20 clips son 6.000 fotogramas,
de los que Ezequiel saca 400–600 imágenes muestreando. Tomar 500 fotos a mano es media
semana perdida.

| Cuántos | Qué se graba | Nombre del archivo |
|---|---|---|
| 8 | Una mano deja caer la gasa en el **recipiente rojo** | `rojo_01.mp4` … `rojo_08.mp4` |
| 8 | Una mano deja caer la gasa en el **recipiente común** | `comun_01.mp4` … `comun_08.mp4` |
| 2 | La gasa **pasa cerca de la boca pero no cae dentro**: se acerca, duda y se retira | `negativo_01.mp4`, `negativo_02.mp4` |
| 2 | La escena **vacía**, sin gasa ni manos | `vacio_01.mp4`, `vacio_02.mp4` |

Los cuatro últimos no son relleno: son los que permiten medir eventos falsos (RNF-07) y
los que evitan que el modelo detecte una gasa donde no hay nada. Sin ellos, el número de
«tasa de eventos falsos» del informe no se puede calcular.

### Varía entre tomas

No grabes veinte veces lo mismo. Cambia en cada clip al menos una cosa:

- La mano que descarta: izquierda, derecha, desde arriba, desde el costado.
- La velocidad: un descarte rápido y uno lento.
- La forma de la gasa: arrugada, abierta, doblada.
- La posición de la mano al soltar: sobre el centro de la boca o sobre el borde.
- Un par de clips con un poco menos de luz (una lámpara menos).

Si todos los clips son idénticos, el modelo aprende ese caso y falla con cualquier otro.

---

## 3. Dónde van

```
datos/videos/rojo_01.mp4
datos/videos/comun_01.mp4
datos/videos/negativo_01.mp4
datos/videos/vacio_01.mp4
```

Los videos **no se suben al repositorio** (están en el `.gitignore`: pesan y Git no es
para eso). Se comparten por Drive y cada uno los pone en su carpeta `datos/videos/`
local. Deja el enlace en `docs/bitacora.md`.

---

## 4. Comprobación antes de dar la tarjeta por hecha

```bash
python herramientas/verificar_videos.py
```

El script cuenta los clips por tipo, mide duración, fps y resolución, y avisa si falta
algo. La tarjeta BVIA-32 se mueve a «En revisión» cuando el script no reporta ningún
problema **y** Ezequiel confirma que puede extraer fotogramas (BVIA-38).

---

## 5. Cuando sí tengamos acceso al laboratorio

Este montaje es un sustituto, no el escenario real. Cuando el laboratorio autorice la
instalación hay que **volver a grabar** en el puesto real y reentrenar: el fondo, la
luz, la altura y el tipo de recipiente serán distintos y el modelo entrenado aquí no se
transfiere directamente. Eso ya está anotado como limitación en el informe del
componente práctico, y por eso el OE1 habla de capturar en el propio puesto de trabajo.

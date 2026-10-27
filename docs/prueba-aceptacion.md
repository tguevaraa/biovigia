# Prueba de aceptación del MVP

**Tarea BVIA-33 · Responsable: Tommy Guevara · Día 10 (09/11/2026)**

Un solo criterio decide si el MVP está terminado. No hay interpretación ni puntos
parciales: o los diez descartes pasan, o no está.

---

## El criterio

> Con la cámara apuntando al montaje, **diez descartes seguidos** —cinco al recipiente
> rojo y cinco al común— producen **diez eventos en el tablero con el veredicto
> correcto**. El recipiente común queda **marcado como contaminado** con su evidencia
> recortada, y al **registrar el recambio** vuelve a estado normal.

---

## Preparación (el día anterior)

- [ ] La base de datos pasó de SQLite a PostgreSQL y las migraciones corren limpias.
- [ ] El montaje está en su sitio, con la cámara en la misma posición que cuando
      Francisco trazó los polígonos. Si se movió, hay que volver a trazarlos.
- [ ] `zonas.json` tiene los dos polígonos y el servicio de visión los dibuja encima de
      la imagen en vivo.
- [ ] El modelo cargado es `vision/modelos/biovigia-gasa-v0.1.pt`, no `yolov8n.pt` sin
      ajustar.
- [ ] Existen las tres cuentas de prueba: una por rol.
- [ ] La base está limpia: sin eventos de prueba ni del simulador.

---

## El recorrido

| # | Paso | Qué debe pasar |
|---|---|---|
| 1 | Descartar la gasa en el **rojo**, cinco veces seguidas | Aparecen cinco eventos con veredicto **conforme**. El recipiente rojo sigue en estado normal. |
| 2 | Descartar la gasa en el **común**, cinco veces seguidas | Aparecen cinco eventos con veredicto **no conforme**. |
| 3 | Mirar el tablero (PAN-02) | Diez eventos en total, los indicadores cuadran y el recipiente común aparece marcado como **contaminado**. |
| 4 | Abrir uno de los eventos no conformes (PAN-04) | Se ve la **evidencia recortada** del recipiente, con la confianza y la hora. El recorte no incluye el fotograma completo ni caras. |
| 5 | Entrar como **personal de limpieza** y abrir PAN-05 | Se ve el recipiente común contaminado, con la hora desde la que lo está. No se ve el enlace al evento. |
| 6 | Registrar el recambio (PAN-06) | El recipiente vuelve a **normal** y el evento se conserva en el historial. |
| 7 | Intentar registrar el recambio otra vez | El sistema lo rechaza con el aviso informativo, no con un error. |
| 8 | Entrar como personal de limpieza a la dirección de PAN-03 | Aparece el aviso de acceso no autorizado y el botón que devuelve a su pantalla inicial. |

**Pasa la prueba si los ocho pasos salen sin tocar nada a mano, en un solo recorrido.**
Si hay que reiniciar un servicio a la mitad, no pasó.

---

## Qué anotar aunque pase

Anota en `docs/bitacora.md` lo que haya costado:

- Cuántos descartes hubo que repetir porque el sistema no los detectó.
- Si se generó algún evento que no correspondía a un descarte real.
- Cuánto tardó el evento en aparecer en el tablero.

Esos tres números son los que después se convierten en la exactitud de asignación
(RNF-08), la tasa de eventos falsos (RNF-07) y la latencia de registro (RNF-24) del
informe. No los inventes al final: mídelos aquí.

---

## La demo

Tres minutos, un solo recorrido, sin improvisar. Guion:

1. **Quince segundos** — qué problema resuelve: el paciente bota la gasa en el recipiente
   equivocado y nadie lo registra.
2. **Treinta segundos** — el montaje y las zonas trazadas sobre la imagen.
3. **Noventa segundos** — los descartes en vivo: uno al rojo (conforme), uno al común
   (no conforme), el recipiente que se marca, la evidencia recortada.
4. **Treinta segundos** — la vista del personal de limpieza y el recambio que cierra el
   ciclo.
5. **Quince segundos** — qué viene después: las tres clases, el conjunto de datos
   completo, los reportes y el dispositivo de borde.

Graba la pantalla y el montaje a la vez si puedes. Si no, graba la pantalla y apunta la
cámara del teléfono al montaje en la parte de los descartes.

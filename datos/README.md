# datos/ — Videos, imágenes y anotaciones (Tommy y Ezequiel)

Nada de lo que hay aquí, salvo este archivo y `dataset.ejemplo.yaml`, va al repositorio:
los videos y las imágenes pesan demasiado y se comparten por Drive (ver `docs/bitacora.md`).

| Carpeta | Qué va | Cómo se llena |
|---|---|---|
| `videos/` | Los 20 clips de BVIA-32 (`rojo_01.mp4`…) | Grabación del montaje (`docs/escena-montaje.md`) |
| `imagenes/` | Fotogramas para anotar | `python herramientas/extraer_fotogramas.py` |
| `dataset/` | Imágenes y etiquetas YOLO partidas 80/20 | Exportación de la herramienta de anotación |
| `runs/` | Salidas del entrenamiento | `python herramientas/entrenar_modelo.py` |
| `sinteticos/` | Videos generados para pruebas sin cámara | `python herramientas/generar_video_sintetico.py --todos` |

Clases (en este orden): `gasa`, `recipiente_rojo`, `recipiente_comun` y, opcional, `mano`.
Si el modelo se entrena con `mano`, el servicio activa solo el disparador por mano
(`docs/deteccion-dos-etapas.md`); sin ella funciona como antes.

**Partición por video, no por imagen.** Dos fotogramas seguidos del mismo clip son casi
idénticos: si uno cae en entrenamiento y el otro en validación, el mAP sale inflado.
Reserva 4 de los 20 videos (uno de cada tipo) completos para validación.

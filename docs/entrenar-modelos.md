# Cómo entrenar los modelos de visión

**Autor: Tommy Guevara · 22/11/2026 · Rama `vision/deteccion-dos-etapas`**

Guía para que cualquiera del equipo pueda entrenar los modelos de BioVigIA (gasas, tachos,
jeringas, curitas…) igual que se viene haciendo, medirlos y probarlos en vivo. Si trabajas
con Claude, lee también la [sección 9](#9-si-trabajas-con-claude).

---

## 0. Pasos para entrenar un objeto nuevo (resumen)

Es el camino que funcionó con la gasa: **clips propios + un clic por clip**. Las imágenes
de internet sirven poco (ver la [sección 8](#8-lo-que-se-probó-y-no-funcionó)). El ejemplo
usa `jeringa`; para curitas cambia `jeringa` por `curita` en cada comando.

Todos los comandos van **desde la raíz del repo**, con el entorno activado
(`.\.venv\Scripts\activate`). Si el equipo no está preparado, haz antes la
[sección 2](#2-preparar-el-equipo-una-vez).

**1. Grabar clips con el objeto** (en la sala y con la cámara donde se va a usar):

```powershell
python herramientas/grabar_clips.py --tomas objeto --salida datos/videos/jeringas --prefijo jeringa
```

- En pantalla aparece la toma sugerida: cerca, lejos, al tacho, al piso, delante del
  cuerpo, con luz apagada, otra persona, dos a la vez…
- **Espacio** graba y corta · **n** salta la toma · **q** sale. Clips de 10–20 s.
- Graba **dos rondas** de las 10 tomas, con **ropa distinta** en cada ronda.

**2. Grabar la misma escena sin el objeto** (enseña qué NO es una jeringa):

```powershell
python herramientas/grabar_negativos.py --segundos 90 --salida datos/externos/jeringas-negativos --prefijo neg
```

Durante esos 90 s no debe verse ninguna jeringa. La gente puede moverse normalmente.

**3. Marcar el objeto con un clic por clip:**

```powershell
python herramientas/marcar_con_un_clic.py --videos datos/videos/jeringas --salida datos/externos/jeringas-propias --clase jeringa --val jeringa_12 jeringa_15 jeringa_18
```

- `--val`: 3 o 4 clips **de la segunda ronda** que no se usan para entrenar (sirven para
  medir). Elige tomas distintas: lejos, al tacho, luz apagada…
- En cada clip: mueve la barra a **un** fotograma donde el objeto se vea bien, **un clic en
  el centro de cada objeto** visible (no en los dedos) y **Enter**. Mover la barra después
  borra los clics. `s` salta el clip, `Esc` termina (lo marcado queda guardado).
- Al final SAM 2 lo sigue solo por cada clip. **Abre `datos/externos/jeringas-propias/muestra.jpg`**
  y revisa que las cajas estén sobre el objeto.

**4. Armar el dataset:**

```powershell
python herramientas/armar_dataset_tachos.py --clase jeringa --salida datos/externos/jeringas-v0.1 --fuente propias=datos/externos/jeringas-propias --negativas neg=datos/externos/jeringas-negativos
```

Si tienes descargado Open Images (sección 4, paso 1), suma más negativos con
`--negativas oi=datos/externos/openimages --max-negativas 800`.

**5. Entrenar** (unos 30–50 min con GPU NVIDIA; desde `datos\runs`):

```powershell
cd datos\runs
python ..\..\herramientas\entrenar_modelo.py --datos ..\externos\jeringas-v0.1\dataset.yaml --epocas 60 --nombre biovigia-jeringas-v0.1 --dispositivo 0 > entrenamiento-jeringas-v0.1.log 2>&1
cd ..\..
```

Al terminar, el modelo queda en `vision/modelos/biovigia-jeringas-v0.1.pt`.

**6. Medir con los clips de validación.** Crea `datos/externos/jeringas-val.yaml`:

```yaml
path: C:/Users/<tu-usuario>/dev/biovigia/datos/externos/jeringas-propias
train: val/images
val: val/images
names:
  0: jeringa
```

y corre:

```powershell
python herramientas/entrenar_modelo.py --datos datos/externos/jeringas-val.yaml --solo-evaluar vision/modelos/biovigia-jeringas-v0.1.pt
python herramientas/medir_falsos_positivos.py vision/modelos/biovigia-jeringas-v0.1.pt --carpeta datos/externos/jeringas-negativos/prueba/images
```

Lo que buscamos: **mAP@0,5 ≥ 0,80** en los clips de validación y **0 %** de fotos con
falsos positivos. Si no llega, mira en qué tomas falla y graba más de esas (con la gasa,
la caída delante del cuerpo se arregló así: de 0,13 a 0,94).

**7. Probarlo en vivo con la cámara:**

```powershell
python herramientas/probar_modelo.py --objeto vision/modelos/biovigia-jeringas-v0.1.pt
```

Muestra el objeto en la mano, cerca y lejos, delante del cuerpo y tirándolo al tacho.
Prueba también **sin** el objeto: no debería aparecer ninguna caja. `q` sale.

**8. Compartir el resultado:**

- El `.pt` **no va a git**: pásalo por Drive o USB a quien integra el sistema.
- Anota en la [sección 7](#7-resultados-hasta-hoy) de esta guía el mAP, los falsos
  positivos y cuántos clips usaste.
- Para mejorar una versión: graba más clips, márcalos con otra carpeta de salida, súmala
  con otra `--fuente` en el paso 4 y entrena `v0.2`. **Nunca** sobrescribas una versión.

> **Integrarlo al servicio de visión** (que los eventos cuenten jeringas o curitas) es otro
> paso: hoy las reglas solo confirman descartes de gasa. Cuando el modelo pase el paso 6,
> avísenle a Tommy.

---

## 1. Qué modelos hay y para qué

El sistema usa tres detectores YOLO a la vez, cada uno con una sola tarea:

| Modelo | Detecta | De dónde salen los datos | Estado |
|---|---|---|---|
| `biovigia-tachos-v0.2.pt` | `recipiente` (cualquier tacho de interior) | Open Images + LVIS (internet, sin dibujar nada) | El mejor de tachos. Débil con el balde rojo visto desde arriba y con mucha luz |
| `biovigia-gasas-v0.1.pt` | `gasa` | LVIS: vendas, papel tisú y toalla de papel (no existe un dataset público de gasas) | No reconoce gasas reales: lo que marca son objetos blancos |
| `biovigia-gasas-v0.2.pt` | `gasa` | Lo mismo que v0.1, más fotos del cuarto **sin gasas** como negativos | Sin falsos positivos en el cuarto, pero **tampoco reconoce gasas reales** |
| `biovigia-gasas-v0.3.pt` | `gasa` | v0.2 + ~900 gasas reales de los clips propios, marcadas con un clic por clip ([sección 5](#5-gasas-reales-con-un-clic-por-clip)) | Reconoce las gasas de los clips grabados desde arriba (0,93), pero no las del cuarto (0,006) |
| `biovigia-gasas-v0.4.pt` | `gasa` | v0.3 + 865 gasas del cuarto (10 clips grabados con `grabar_clips.py`, un clic por clip) | Reconoce la gasa en el cuarto (0,93) y en los clips cenitales (0,94), pero no delante del cuerpo (0 de 73) |
| `biovigia-gasas-v0.5.pt` | `gasa` | v0.4 + 531 gasas **delante del cuerpo** (12 clips con `grabar_clips.py --tomas cuerpo`, dos camisetas) | Delante del cuerpo 0,94; en el cuarto 0,96. Marcaba como gasa el puño que agarra un tubo (42 % de los fotogramas de tubos) |
| `biovigia-gasas-v0.6.pt` | `gasa` | v0.5 + 2.925 fotogramas de los clips de **tubos** como negativos (puños, tubo, piso) | **El que usa la demostración.** 0 % de falsos sobre tubos y puños; delante del cuerpo 98 %; ver la [sección 7](#7-resultados-hasta-hoy) |
| `biovigia-tubos-v0.10.pt` | `tubo` | Tubos propios (derecho, de cabeza, piso, agarres) + gasas de canto como negativos | Sin falsos sobre gasas, pero en el montaje de la demostración (tubo chico, junto a los tachos) solo lo ve en el 3 % de los fotogramas |
| `biovigia-tubos-v0.11.pt` | `tubo` | v0.10 + 237 fotogramas del **montaje** (`grabar_clips.py --tomas tubo-montaje`, ×3) + 600 negativos de los clips de gasa y jeringa del mismo montaje | **El que usa la demostración.** Montaje 91 % (v0.10: 3 %); ver la [sección 7](#7-resultados-hasta-hoy) |
| `yolo11n-coco.pt` | `persona` | El YOLO original de COCO, sin reentrenar | Funciona bien; no hace falta entrenarlo |

Los pesos (`.pt`) **no van a git** (`vision/modelos/*.pt` está en `.gitignore`). Para
usar un modelo que entrenó otra persona, pásenlo por el medio que use el equipo y déjenlo
en `vision/modelos/`.

**Por qué no se dibujan polígonos sobre los tachos.** Si alguien mueve un tacho o la
cámara, el polígono queda mal. El sistema tiene que reconocer el tacho por lo que es, y
la lógica de eventos se aplica a partir de esa detección. Por eso todo el trabajo va a que
los modelos reconozcan los objetos, no a marcar zonas fijas.

## 2. Preparar el equipo (una vez)

Probado en Windows 11 con una RTX 2070 (8 GB). Sin GPU también funciona, pero un
entrenamiento pasa de ~20 minutos a varias horas.

```powershell
cd C:\Users\<tu-usuario>\dev\biovigia
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-vision.txt
```

`pip` instala torch **sin CUDA**. Para usar la GPU, reemplázalo por la versión con CUDA
que soporte tu driver. Mira el driver con `nvidia-smi`. Con un driver que soporta CUDA 13.x:

```powershell
pip install --force-reinstall --no-deps torch==2.15.0+cu132 torchvision==0.29.2+cu132 --index-url https://download.pytorch.org/whl/cu132
```

Comprueba que la ve:

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**Problemas conocidos en Windows:**

| Síntoma | Causa | Solución |
|---|---|---|
| `No module named 'cv2'` / `'decouple'` | El entorno virtual no está activado | `.\.venv\Scripts\activate` desde la raíz del repo, o llamar a `.\.venv\Scripts\python.exe` directamente |
| `UnicodeEncodeError: 'charmap' codec…` al imprimir ✓ o ▸ | La consola usa cp1252 | `$env:PYTHONIOENCODING = "utf-8"` antes de correr la herramienta |
| App Control / Device Guard bloquea `caffe2_nvrtc.dll` | Política de la máquina, intermitente | Reintentar. **No desactivar** la política: si persiste, pedir permiso a TI |
| `MemoryError` de numpy a mitad del entrenamiento | Demasiados procesos cargando imágenes | Usar `--trabajadores 2` (es el valor por defecto) y retomar con `--retomar` |

## 3. Dónde vive cada cosa

Todo lo que pesa está fuera de git, dentro de `datos/`:

```
datos/
  videos/            clips propios: rojo_01..08, comun_01..08, negativo_01..02, vacio_01..02
    cuarto/          clips del cuarto con la gasa (cuarto_01..30, grabar_clips.py)
  externos/          descargas de internet y negativos propios
    openimages/      contenedores de basura y personas (Open Images V7)
    lvis/            tachos y baldes de interior (LVIS)
    lvis-gasas/      sustitutos de gasa (LVIS: bandage, tissue_paper, paper_towel)
    cuarto/          fotos de la escena SIN gasas (train / val / prueba)
    gasas-propias/   gasas reales de los clips cenitales, marcadas con un clic (clics.json, train, val)
    gasas-cuarto/    gasas reales del cuarto, marcadas con un clic (val = clips 22, 23, 27, 29)
    tachos/          dataset armado de tachos (dataset.yaml)
    gasas/           dataset armado de gasas v0.1
    gasas-v0.2/      dataset armado de gasas v0.2 (con los negativos del cuarto)
    gasas-v0.3/      dataset armado de gasas v0.3 (con las gasas reales)
    gasas-v0.4/      dataset armado de gasas v0.4 (más las gasas del cuarto)
  anotaciones/       pre-anotaciones y exportaciones de CVAT
  runs/              cada entrenamiento: pesos, gráficas y su .log
vision/modelos/      los .pt que usan el servicio y la demostración
```

## 4. El flujo completo

```
 1. Bajar imágenes públicas ─┐
 2. Grabar negativos propios ┼─► 3. Armar el dataset ─► 4. Entrenar ─► 5. Medir ─► 6. Probar en vivo
 (más adelante) CVAT ────────┘                                            │
                                                                          └─► si empeora, no se usa
```

Cada paso es una herramienta de `herramientas/`. Todas aceptan `--help`.

### Paso 1 · Imágenes públicas (solo la primera vez)

```powershell
python herramientas/descargar_openimages.py
python herramientas/descargar_lvis.py
python herramientas/descargar_lvis.py --categorias bandage tissue_paper paper_towel --salida datos/externos/lvis-gasas
```

- Open Images baja un CSV de 2,26 GB mientras lo filtra. La primera vez tarda; después
  usa la copia filtrada.
- Las licencias son CC BY. **Hay que citar** Open Images (Kuznetsova et al., IJCV 2020),
  LVIS (Gupta et al., CVPR 2019) y COCO en el informe.

### Paso 2 · Negativos de la escena real

Es lo que más ayuda contra los falsos positivos. Graba la escena donde va a estar la
cámara **sin el objeto a la vista** (sin gasas), con gente moviéndose normalmente:

```powershell
python herramientas/grabar_negativos.py --segundos 90
```

- Guarda un fotograma cada 0,5 s y lo reparte por tiempo: 70 % a `train`, 15 % a `val` y
  15 % a `prueba`. La prueba **no se usa para entrenar**; sirve para medir en el paso 5.
- Con la cámara del teléfono (Iriun), descarta solos los fotogramas negros del inicio.
- Si cambian de lugar (laboratorio, otra sala), graben otra carpeta:
  `--salida datos/externos/laboratorio --prefijo lab`.
- Un clip ya grabado también sirve: `--video datos/videos/vacio_01.mp4`.

### Paso 3 · Armar el dataset

`armar_dataset_tachos.py` junta fuentes en un dataset de **una sola clase**. Las imágenes
se enlazan (no se copian), así que no ocupa disco extra.

Tachos:

```powershell
python herramientas/armar_dataset_tachos.py
```

Gasas, con los negativos de internet y los del cuarto:

```powershell
python herramientas/armar_dataset_tachos.py --clase gasa --salida datos/externos/gasas-v0.2 --fuente lvisg=datos/externos/lvis-gasas --negativas oi=datos/externos/openimages --max-negativas 800 --negativas cuarto=datos/externos/cuarto
```

- `--fuente prefijo=carpeta` agrega imágenes **con** cajas (se usa su clase 0).
- `--negativas prefijo=carpeta` agrega imágenes **sin** cajas: enseñan qué no es el objeto.
- Usa una carpeta de salida nueva por versión (`gasas-v0.3`, …). Así la versión anterior
  se puede volver a entrenar igual.

### Paso 4 · Entrenar

**Córrelo desde `datos/runs/`**, así el `yolo11n.pt` que baja Ultralytics queda ahí y no
en la raíz del repo:

```powershell
cd datos\runs
python ..\..\herramientas\entrenar_modelo.py --datos ..\externos\gasas-v0.2\dataset.yaml --epocas 60 --nombre biovigia-gasas-v0.2 --dispositivo 0 > entrenamiento-gasas-v0.2.log 2>&1
```

- Al terminar copia el mejor peso a `vision/modelos/<nombre>.pt` e imprime el mAP@0,5 y
  los criterios del OE2 y el RNF-11 (≤ 3 M de parámetros, ≤ 5 GFLOPs).
- 60 épocas con ~2.500 imágenes tardan ~20–25 minutos en la RTX 2070.
- Si se corta: el mismo comando con `--retomar` sigue desde la última época.
- `--luz fuerte` aumenta mucho las variaciones de brillo y color. **Con datos de internet
  empeoró** la escena real (ver la [sección 8](#8-lo-que-se-probó-y-no-funcionó)).
  Resérvalo para cuando haya clips propios con luces distintas.
- `--imgsz 512` baja los GFLOPs por debajo de 5 (requisito RNF-11). Hay que inferir
  también a 512.
- **Nombres:** `biovigia-<objeto>-vX.Y`. Nunca se sobrescribe una versión: se sube el
  número. Guarda el `.log` con el mismo nombre.

### Paso 5 · Medir antes de usar

Un modelo nuevo se compara **siempre contra el anterior, con la misma prueba**. Hay tres
mediciones, y ninguna sola alcanza:

| Qué mide | Herramienta | Bueno si… |
|---|---|---|
| Que siga viendo el objeto | el mAP@0,5 que imprime `entrenar_modelo.py` (o `--solo-evaluar modelo.pt`) | no baja respecto de la versión anterior |
| Falsos positivos en la escena real | `python herramientas/medir_falsos_positivos.py vision/modelos/viejo.pt vision/modelos/nuevo.pt` | baja el % de fotos con alguna caja falsa |
| Sensibilidad a la luz | `python herramientas/evaluar_luz.py --objeto gasas` (o sin `--objeto` para tachos) | no cae más que el anterior con luz simulada |

Anoten los números en `docs/bitacora.md` o en el resumen de la sesión, con la fecha y el
nombre del modelo.

### Paso 6 · Probarlo en vivo

```powershell
python herramientas/probar_modelo.py
python herramientas/probar_modelo.py --modelo-gasas vision/modelos/biovigia-gasas-v0.2.pt
python herramientas/probar_modelo.py --fuente datos/videos/rojo_01.mp4
```

- **Colores de las cajas:** rojo = tacho, celeste = gasa, naranja = persona. Una línea
  fina significa que el objeto no se vio en ese fotograma y se mantiene un momento (estabilizador).
- **Opciones:**
  - `--sin-estabilizar` muestra lo que da el modelo fotograma a fotograma.
  - `--con-recortes` activa la búsqueda de gasas en recortes alrededor de personas y
    tachos (etapa 2). Con v0.1 no ayudaba.
  - `--area-max-gasa` descarta las gasas demasiado grandes (por defecto, más del 2 % de la imagen).
- Sale con `q` o `Esc`. Si la ventana queda negra, revisa que Iriun esté conectado y que
  ningún otro programa use la cámara.

## 5. Gasas reales con un clic por clip

No hay imágenes públicas de gasas, y los detectores que buscan por texto (YOLO-World,
YOLOE) no encuentran una gasa en la mano: se probó con «gauze», «cotton pad», «tissue» y
otras, y no la marcaron nunca. Alguien tiene que indicar dónde está la gasa, pero basta
**un clic por clip**: SAM 2 (Meta, vía Ultralytics) la sigue sola por todo el video.

```powershell
cd datos\runs
python ..\..\herramientas\marcar_con_un_clic.py --videos ..\videos --patron "[rcn]*.mp4" --salida ..\externos\gasas-propias
```

En la ventana, para cada clip:

1. Mueve la barra hasta un fotograma en que se vea bien la gasa.
2. **Un clic en el centro de cada gasa visible** (no en los dedos). Cada clic es una gasa.
3. **Enter** para confirmar. Si no avanza, haz clic en la imagen para darle el foco.
   `r` borra los clics, `s` salta el clip y `Esc` termina.

SAM la sigue hacia adelante y hacia atrás desde el clic. Se descartan solas las cajas
dudosas: máscaras salpicadas, cajas que cambian mucho de tamaño y tiras (el borde de un
tacho). Los clics quedan en `clics.json`: con `--repetir` se rehace todo sin volver a
hacer clic. **Revisa `muestra.jpg` antes de entrenar.**

Después se suma como una `--fuente` más en el paso 3:

```powershell
python herramientas/armar_dataset_tachos.py --clase gasa --salida datos/externos/gasas-v0.3 --fuente propias=datos/externos/gasas-propias --fuente lvisg=datos/externos/lvis-gasas --negativas oi=datos/externos/openimages --max-negativas 800 --negativas cuarto=datos/externos/cuarto
```

Para medir **solo con gasas reales** (un clip que no se usa para entrenar, `rojo_08`):

```powershell
python herramientas/entrenar_modelo.py --datos datos/externos/gasas-reales-val.yaml --solo-evaluar vision/modelos/biovigia-gasas-v0.3.pt
```

**Grabar clips de una escena nueva.** Un modelo solo reconoce la gasa en escenas parecidas
a las que vio: v0.3 (clips cenitales) no la veía en el cuarto; v0.4, con 10 clips del cuarto,
sí. Para el laboratorio hay que repetir esto allí, con la cámara en la esquina alta:

```powershell
python herramientas/grabar_clips.py --salida datos/videos/laboratorio --prefijo lab
```

Muestra en pantalla la toma sugerida (gasa cerca, lejos, al tacho, al piso, luz apagada,
otra persona…). Espacio graba y corta; `n` salta la toma. Con una ronda de 10 tomas de
10–20 s alcanzó para el cuarto; graben una segunda ronda y guarden 3 o 4 clips para
validar (`--val` en `marcar_con_un_clic.py`), así se mide en la escena real.

Al marcar: **un solo fotograma por clip** y un clic en cada gasa de ese fotograma. Mover la
barra después borra los clics, porque SAM los aplica todos a ese fotograma.

### Datos propios con CVAT (alternativa)

Si se quieren revisar las cajas a mano, el modelo pre-anota y una persona solo corrige:

```powershell
python herramientas/preanotar.py
python herramientas/preanotar_gasas.py
```

- `preanotar.py` (tachos) deja en `datos/anotaciones/preanotacion/` un `<grupo>_imagenes.zip`
  y un `<grupo>_yolo.zip`.
- `preanotar_gasas.py` (gasas) deja `<grupo>_gasas_yolo.zip` con los mismos fotogramas.

En CVAT (proyecto BioVigIA, etiquetas `gasa`, `recipiente_rojo`, `recipiente_comun`, `mano`):

1. Crear la tarea con el zip de imágenes.
2. *Actions → Upload annotations → YOLO 1.1* con el zip de tachos (modo **Replace**).
3. Repetir con el zip de gasas en modo **Append**, para no borrar los tachos.
4. Revisar fotograma por fotograma: corregir, agregar lo que falta y borrar lo que sobra.
5. *Export task dataset → YOLO 1.1* y dejar el zip en `datos/anotaciones/`.

Las tres tareas actuales (rojo, comun, negativo_vacio) están pre-anotadas y esperan
revisión. Ojo: sus gasas las propuso v0.1, que no reconocía gasas reales, así que hay que
revisarlas con cuidado. Convertir la exportación de CVAT en una `--fuente` todavía no
tiene herramienta propia.

**Qué conviene grabar para la próxima tanda:**
- La cámara **en la esquina alta**, donde va a quedar.
- Gasas **a varias distancias**: de cerca y del otro lado de la sala.
- **Luces distintas:** luz apagada, sol, lámpara.
- Exposición y balance de blancos **bloqueados** en la app de la cámara.

## 6. Cómo leer los resultados

- **mAP@0,5** (0 a 1): qué tan bien encuentra el objeto en las imágenes de validación. La
  meta del OE2 es ≥ 0,80. Con gasas, el número que vale es el de **gasas reales**
  (`gasas-reales-val.yaml`); el de validación mezcla los sustitutos de LVIS.
- **% de fotos con falso positivo:** sobre fotos donde el objeto no está, cualquier caja
  es un error. Se mide a la confianza de la demostración (0,35) y a otras.
- Un modelo que baja los falsos positivos pero también el mAP **no es mejor**: aprendió a
  no ver nada.

## 7. Resultados hasta hoy

| Modelo | mAP@0,5 (val) | mAP@0,5 en gasas reales (`rojo_08`) | Falsos positivos en el cuarto (conf 0,35) | Gasa en la mano en el cuarto (57 fotos) | Notas |
|---|---|---|---|---|---|
| tachos-v0.2 | 0,599 (0,744 en OI / 0,548 en LVIS) | — | — | — | Con sobreexposición solo en el 7 % de los fotogramas ve los 2 tachos |
| tachos-v0.3 (`--luz fuerte`) | 0,594 | — | — | — | Igual en validación pero peor en la escena propia; descartado |
| gasas-v0.1 | 0,364 | 0,015 | **60 %** de las fotos | 0 de 57 | Marcaba un tacho blanco (0,6) y un teclado (0,3) como gasa |
| gasas-v0.2 | 0,413 (en la validación de v0.1) | 0,133 | 0 % | 0 de 57 | v0.1 + 249 negativos: 120 fotos del cuarto y 129 de los clips vacíos. 60 épocas, 25 min |
| gasas-v0.3 | 0,616 (mezcla LVIS y reales) | 0,928 | 0 % | 0 de 57 (máx. 0,11) | v0.2 + 892 gasas reales de 14 clips, con un clic por clip. 60 épocas, 32 min. En los clips del cuarto: 0,006 |
| gasas-v0.4 | 0,791 | 0,944 | 0 % | 29 de 57 (mediana 0,55) | v0.3 + 865 gasas de 10 clips del cuarto. En los 4 clips de validación del cuarto: 0,933. **Delante del torso: 0 de 73** |
| gasas-v0.5 | **0,824** ✓ OE2 | 0,942 | **0 %** | — | v0.4 + 531 gasas delante del cuerpo. **Validación del cuerpo (`gasas-cuerpo-val.yaml`): 0,944** (v0.4: 0,132). Cuarto: 0,955. Delante del torso: 50 de 73; al costado: 404 de 408. 60 épocas, 50 min |
| **gasas-v0.6** | **0,835** ✓ OE2 (en la validación de v0.5) | — | **0 %** | — | v0.5 + 2.925 negativos de los clips de tubos (800 normales, 800 agarres, 800 piso, 525 lanzamientos). Falsos sobre tubos y puños (617 fotos de validación): **0 %** (v0.5: 42 %). Gasa en el cuarto 96 %, delante del cuerpo 98 % (v0.5: 92 %). 60 épocas, 72 min |
| **tubos-v0.11** | 0,588 (validación nueva, con el montaje y 754 negativos) | — | **0 %** | — | A conf 0,35, v0.10 → v0.11: tubo en el montaje (`tubo4_02`, no visto) 3 % → **91 %**; derecho 73 → 75 %; de cabeza 66 → 76 %; quemado 55 → 59 %; dedos en las puntas 65 → 74 %; tapa en el puño 100 → 97 %. Falsos: cuarto y gente 0 %, gasa de canto 0 %, 249 fotos de los primeros clips de prueba 0 %. Parte de v0.10, 40 épocas, ~55 min |

Sobre gasas-v0.3 y v0.4: `rojo_08` es de la misma sesión que los clips cenitales de
entrenamiento, y los 4 clips de validación del cuarto (`gasas-cuarto-val.yaml`: lejos, al
tacho, luz apagada, otra persona) son de la misma tarde que los de entrenamiento. Miden
bien esas escenas, no otras: **en el laboratorio hay que grabar y marcar clips de allí.**
Las 57 fotos «gasa en la mano» son de otra grabación anterior (otra luz, otro momento): ahí
v0.4 la encuentra en 29, y en varias de las otras la gasa está tapada o fuera de cuadro.

Sobre gasas-v0.2: las 30 fotos de prueba son de la misma grabación de 90 s que los
negativos de entrenamiento (mismo cuarto, misma luz, otros segundos). Que dé 0 % ahí no
garantiza lo mismo en el laboratorio: antes de usarlo allí, graben negativos de esa sala.

**Ninguno de los dos modelos de gasas reconoce una gasa real** (medido el 22/11/2026 con
57 fotos de una gasa en la mano, de cerca). v0.1 marcaba algo chico en 40 de ellas, pero
siempre era el tacho blanco del piso, nunca la gasa. v0.2 no le da a la gasa más de 0,04
de confianza. Los sustitutos de LVIS (vendas, papel tisú) no se parecen a una gasa
doblada: hace falta entrenar con fotos de gasas reales.

## 8. Lo que se probó y no funcionó

Para no repetirlo:

- **Solo Open Images para tachos:** son contenedores de calle. Fallaba en interiores hasta
  que se sumó LVIS.
- **Aumentación fuerte de color (`--luz fuerte`, v0.3):** empeoró la detección en la escena
  propia. CLAHE (ecualizar el contraste) también empeoró.
- **Buscar gasas en recortes alrededor del tacho con gasas-v0.1:** 0 % de mejora. El modelo
  solo reconoce gasas en una escala muy concreta. El recorte en sí funciona (devolver la
  escena a su tamaño recupera la gasa de 0,4 % a 9,2 %), así que hay que volver a medirlo
  con un modelo entrenado con gasas reales.
- **Confiar solo en el mAP de gasas:** v0.1 tenía 0,36 en LVIS y en vivo todo lo que
  marcaba era falso (la mano entera, un tacho blanco). Nunca encontró la gasa real.
- **Entrenar gasas con sustitutos de internet (vendas, papel tisú, toalla de papel):** el
  modelo aprende «cosa blanca», no «gasa». Para validar un modelo de gasas, prueben
  siempre con una gasa real en la mano, no solo con el mAP.
- **Detectores por texto (YOLO-World, YOLOE) para marcar gasas solos:** con «gauze»,
  «cotton pad», «tissue» y otras palabras no marcaron nunca la gasa en la mano; YOLOE con
  «tissue» marcaba una bolsa de papel del escritorio. Lo que sí funcionó fue SAM 2 con un clic.
- **Achicar la caja de la persona para que no «tape» la gasa:** las cajas de los dos modelos no
  interactúan en el código. La gasa desaparecía delante del torso porque el modelo de gasas
  casi no tenía ejemplos así (v0.4: 0 de 73); se arregló grabando esas tomas (v0.5: 50 de 73).
- **Un modelo entrenado en una escena no se traslada a otra:** v0.3 reconoce la gasa en los
  clips cenitales (0,93) y no en el cuarto de costado (0 de 57). Graben donde va a estar la cámara.

## 9. Si trabajas con Claude

El proceso de esta guía se hizo con Claude Code. Para que les funcione igual:

**Al empezar**, pídanle que lea esta guía y el estado de los modelos:

> Lee `docs/entrenar-modelos.md` y `docs/deteccion-dos-etapas.md`. Quiero reentrenar el
> modelo de gasas con [lo nuevo]. Antes de entrenar, mide el modelo actual con
> `medir_falsos_positivos.py` para tener con qué comparar.

**Pedidos que funcionaron bien:**
- "Graba negativos de la escena y reentrena el modelo de gasas; compáralo con el anterior."
- "Mide cómo le afecta la luz al modelo nuevo contra el viejo" (`evaluar_luz.py`).
- "Déjame ver en vivo cómo reconoce": abre `probar_modelo.py` y puede capturar la ventana
  para revisar lo que ves.
- "Pre-anota los clips nuevos para CVAT."

**Reglas del repo que Claude debe respetar** (díganselas si no las sigue):
- **No hace commit ni push sin que se lo pidan.** Los cambios quedan sin commitear hasta
  que alguien revise.
- **Ningún commit lleva `Co-Authored-By` ni menciones a Claude.**
- **No sube a git** los `.pt`, los videos ni nada de `datos/`.
- **No desactiva Device Guard / App Control** ni busca cómo saltárselo. Si algo está
  bloqueado, se pide a TI.
- **Nunca muestra el token** de `vision/.env`.
- **Mide antes y después con la misma prueba,** y dice los números aunque el resultado
  sea malo. Un modelo que no mejora no se usa.
- **No inicia sesión en CVAT ni sube archivos por ustedes:** eso lo hacen ustedes en el navegador.

**Para que entrene sin quedarse esperando:** pídanle que corra el entrenamiento en segundo
plano y guarde el `.log` en `datos/runs/`. Mientras tanto puede preparar la medición.

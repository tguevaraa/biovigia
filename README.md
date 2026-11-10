# BioVigIA

Sistema de visión artificial que verifica en qué recipiente se deposita el material de
punción usado en el área de toma de muestras de un laboratorio clínico, y registra cada
descarte como conforme o no conforme.

**Proyecto de Construcción de Software · Grupo 7 · UNEMI · Paralelo 1C**
Tablero: proyecto **BVIA** en Jira · Objetivo actual: **MVP en diez días** (27/10 – 09/11)

---

## Qué es el MVP

> Con la cámara apuntando al montaje, **diez descartes seguidos** —cinco al recipiente
> rojo y cinco al común— producen **diez eventos en el tablero con el veredicto
> correcto**. El recipiente común queda **marcado como contaminado** con su evidencia
> recortada, y al **registrar el recambio** vuelve a estado normal.

Mientras eso no pase, el MVP no está. El detalle está en `docs/prueba-aceptacion.md`.

---

## Arquitectura en una mirada

```
 Cámara ──► C1 Servicio de visión (vision/)            C2 Servidor Django (servidor/)
            captura → detección → reglas → cola  ──HTTPS──►  API v1 → servicios → ORM ──► C3 BD
            (M1)      (M2 YOLO)   (M3 k-de-N)  SQLite        (DRF)   de dominio          C3b evidencia
                                                                 ▲
            Solo salen eventos confirmados y el                  │ HTTPS
            recorte del recipiente: nunca video.            C4 Navegador (PAN-01 … PAN-12)
```

- **Un microservicio** (visión) y **un monolito en capas** (servidor), como en la sección
  9.1 del informe. Se comunican solo por `docs/contrato-api.md`.
- En el servidor, las vistas **no** tienen reglas de negocio: todo vive en
  `servidor/vigilancia/servicios/` (MVT + capa de servicios, sección 9.2).
- En la visión, cada etapa es un módulo: `captura.py` (M1), `deteccion.py` (M2),
  `seguimiento.py` + `reglas.py` (M3), `evidencia.py` + `publicador.py` (M4 y cola).

## Estructura

```
biovigia/
├── servidor/                 Django + DRF — Darlyn (backend) y Cristofer (pantallas)
│   ├── biovigia/             settings, urls
│   ├── cuentas/              usuarios con rol, permisos por rol, bitácora no editable
│   ├── vigilancia/           modelos, servicios de dominio, API v1, comandos, pruebas
│   └── tablero/              pantallas PAN-01…PAN-12, design system, JS del cliente
├── vision/                   Servicio de visión — Francisco
│   ├── modelos/              pesos .pt (no van al repo)
│   └── tests/                pruebas sin cámara (incluye video sintético)
├── datos/                    Videos, imágenes y anotaciones — Tommy y Ezequiel
├── herramientas/             Simulador, extracción, entrenamiento y evaluación
└── docs/                     Contrato de la API, montaje de la escena y bitácora
```

## Documentos que hay que leer antes de escribir código

| Documento | Para quién |
|---|---|
| `docs/contrato-api.md` | **Todos.** Es el acuerdo que permite trabajar en paralelo. |
| `docs/escena-montaje.md` | Tommy y Ezequiel, antes de grabar. |
| `docs/prueba-aceptacion.md` | Todos, para saber cuándo terminamos. |

---

## Arranque (Windows + VS Code)

Requisitos: **Python 3.10 a 3.13**, Git y una cámara web (o un video). Todos los comandos
se ejecutan **desde la carpeta raíz `biovigia`**, en la terminal de VS Code.

```powershell
git clone <url-del-repositorio>
cd biovigia
python -m venv .venv
.venv\Scripts\activate            # Linux o macOS: source .venv/bin/activate
pip install -r requirements-servidor.txt -r requirements-vision.txt
```

En VS Code: `Ctrl+Shift+P` → **Python: Select Interpreter** → elige `.venv`.
Si PowerShell no deja activar el entorno: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Si tu terminal es Git Bash** (el prompt dice `MINGW64`), los comandos cambian:

```bash
source .venv/Scripts/activate      # en vez de .venv\Scripts\activate
cp servidor/env.ejemplo servidor/.env   # en vez de copy
cp vision/env.ejemplo vision/.env
```

### 1. Servidor (terminal 1)

```powershell
cd servidor
copy env.ejemplo .env               # opcional en desarrollo; obligatorio en producción
python manage.py migrate
python manage.py sembrar --cuentas-demo
python manage.py runserver
```

`sembrar` crea el **box-2** con sus dos recipientes, los parámetros por defecto, la cuenta
del servicio de visión e imprime su **token**. Con `--cuentas-demo` crea además una
cuenta por rol (clave `BioVigIA-2026`, solo para desarrollo):

| Usuario | Rol | Pantalla inicial |
|---|---|---|
| `admin.demo` | Administrador | Tablero principal (y Configuración) |
| `supervisor.demo` | Responsable de bioseguridad | Tablero principal |
| `limpieza.demo` | Personal de limpieza | Estado de recipientes (vista móvil) |

Abre http://localhost:8000 · Panel técnico de Django: http://localhost:8000/admin/
(`python manage.py createsuperuser` para entrar ahí).

### 2. Servicio de visión (terminal 2, desde la raíz)

```powershell
copy vision\env.ejemplo vision\.env
# Edita vision\.env y pega el token en BIOVIGIA_TOKEN
#   (si lo perdiste: python servidor\manage.py token_vision --box box-2)
```

Con la escena **vacía** (sin manos ni gasa), envía el fotograma de referencia y traza las
zonas en **Configuración → Zonas de recipientes** (PAN-09). El servicio de visión debe
estar corriendo para que la pantalla reciba los fps de la cámara (HU-01, criterio 3):

```powershell
python -m vision --enviar-referencia
```

Después, arranca el servicio. Mientras no exista el modelo entrenado, usa el detector de
desarrollo (objetos blancos en movimiento):

```powershell
python -m vision --detector movimiento --mostrar      # sin modelo, para probar ya
python -m vision --mostrar                            # con vision/modelos/biovigia-gasa-v0.1.pt
python -m vision --fuente datos\videos\comun_01.mp4 --sin-servidor --mostrar   # un video, sin publicar
python -m vision --editar-zonas                       # editor local, si no hay servidor
```

`--mostrar` abre una ventana con las zonas y las detecciones (tecla `q` para salir). La
vista previa no se graba. Si el servidor se cae, los eventos quedan en
`vision/cola/box-2.sqlite3` y se envían solos al volver (RNF-12).

### 3. Sin cámara: datos de prueba

```powershell
python herramientas\simulador.py --n 20          # 20 eventos al tablero
python herramientas\simulador.py --repetir       # reenvía el lote: todos deben salir duplicados
python herramientas\generar_video_sintetico.py --todos --carpeta datos\sinteticos
python herramientas\evaluar_reglas.py --detector movimiento --videos datos\sinteticos --zonas datos\sinteticos\zonas.json
```

### 4. Pruebas automáticas

```powershell
cd servidor; python manage.py test; cd ..        # 26 pruebas: contrato, roles, aceptación
python -m unittest discover -s vision/tests -t . # 42 pruebas: zonas, reglas, disparador, cola, canalización
```

### Base de datos

El MVP arranca con **SQLite**. El paso a PostgreSQL (BVIA-33) no toca código: instala
`psycopg[binary]`, completa `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` en
`servidor/.env` y vuelve a ejecutar `migrate` y `sembrar`.

---

## Del video al modelo (Ezequiel y Francisco)

| Paso | Comando | Tarjeta |
|---|---|---|
| Verificar los 20 videos | `python herramientas\verificar_videos.py` | BVIA-32 |
| Extraer fotogramas (1 de cada 10) | `python herramientas\extraer_fotogramas.py` | BVIA-38 |
| Anotar `gasa`, `recipiente_rojo`, `recipiente_comun` (y `mano`, opcional) y partir 80/20 **por video** | herramienta de anotación → `datos/dataset/` | BVIA-39 |
| Entrenar y verificar OE2 (mAP, parámetros, GFLOPs) | `python herramientas\entrenar_modelo.py` | BVIA-40 |
| Medir fps en el equipo de despliegue (RNF-09) | `python herramientas\entrenar_modelo.py --solo-evaluar vision\modelos\biovigia-gasa-v0.1.pt --medir-fps` | BVIA-41 |
| Medir RNF-07 y RNF-08 sobre los videos | `python herramientas\evaluar_reglas.py` | BVIA-36 |

Copia `datos/dataset.ejemplo.yaml` como `datos/dataset.yaml` antes de entrenar. Detalles
en `datos/README.md`.

## Cómo decide el sistema que hubo un descarte (M3)

YOLO solo dice dónde hay una gasa en cada fotograma. Quien decide es `vision/reglas.py`:

1. La trayectoria de la gasa **termina dentro** del polígono de un recipiente.
2. **Regla k-de-N:** de sus últimas N observaciones, al menos k están en esa zona
   (por defecto 3 de 5). Una gasa que solo roza la boca y se retira no pasa.
3. La ausencia se **sostiene** durante la ventana de confirmación (1,5 s). Si reaparece
   antes, no se cuenta todavía.
4. **Un evento por gasa**: cada trayectoria se cierra al confirmarse, y una memoria de lo
   ya contado evita repetir una gasa que queda a la vista dentro de un recipiente sin tapa.
5. **Disparador por mano** (opcional): si el modelo distingue la clase `mano`, una gasa
   solo cuenta si apareció junto a una mano cerca de los recipientes. Un reflejo o un
   papel que ya estaba dentro no generan evento. Se controla con `BIOVIGIA_DISPARADOR`
   o `--disparador auto|si|no`; el detalle está en `docs/deteccion-dos-etapas.md`.

Umbral, k, N, ventana y fps se cambian en **PAN-10** y el servicio los aplica en menos de
30 s, sin reiniciar ni reentrenar (RNF-16). Cada evento guarda sus `rasgos` para entrenar
después el clasificador de scikit-learn (`BIOVIGIA_CLASIFICADOR`).

---

## Cómo trabajamos

- **`main` siempre funciona.** Nadie trabaja directamente en `main`.
- **Una rama por persona y por tarea**, nombrada por el área y lo que hace:
  `vision/zonas`, `backend/ingesta`, `frontend/tablero`, `datos/anotacion`.
- **El mensaje de commit empieza con la clave de Jira:**
  `BVIA-34 editor de zonas con cuatro puntos`.
- **Para fusionar, revisa otro integrante.** Es el equivalente de la columna
  «En revisión» del tablero: la tarjeta sale de ahí cuando alguien que no la hizo
  comprueba el criterio «Hecho cuando…» escrito en su descripción.
- **Máximo dos tarjetas en curso por persona.** Si algo te bloquea más de un día, se
  dice en la reunión y se reparte.

### Reunión diaria, quince minutos

Tres preguntas y nada más: qué terminé, qué voy a hacer, qué me bloquea.

---

## Quién hace qué en el MVP

| Integrante | Bloque | Tareas |
|---|---|---|
| Tommy Guevara | Contrato, repositorio, escena e integración | BVIA-30, 31, 32, 33 |
| Francisco Solís | Servicio de visión | BVIA-34, 35, 36, 37 |
| Ezequiel Rosales | Conjunto de datos y modelo | BVIA-38, 39, 40, 41 |
| Darlyn Murillo | Servidor y API | BVIA-42, 43, 44, 45 |
| Cristofer Vergara | Pantallas | BVIA-46, 47, 48, 49 |

---

## Estado de lo que pide el informe

Implementado en el código: las doce pantallas PAN-01 a PAN-12 con los tres roles,
exportación CSV y PDF (HU-04), acciones correctivas (RF-10), usuarios y parámetros desde
la interfaz (RF-11, RF-12), retención automática de evidencia (RNF-17), bitácora no
editable (RNF-14), periodo no observado (RNF-06), cola local (RNF-12), modo oscuro por
tokens, el adaptador de CloudWatch (opcional) y la regla con clasificador de scikit-learn
(opcional, se activa cuando exista un clasificador entrenado).

Depende del equipo y del laboratorio, no del código:

- **El modelo entrenado** `vision/modelos/biovigia-gasa-v0.1.pt` (OE1, OE2). Hasta
  entonces, `--detector movimiento` permite probar todo el flujo; los eventos quedan
  marcados con el modelo `dev-movimiento-v0`.
- **El dispositivo de borde**: el mismo código corre en el portátil y en el borde
  (RNF-21); falta el equipo y la medición de 15 fps allí.
- **TLS en la red interna** (RNF-18): el servidor de desarrollo de Django es HTTP. En el
  piloto se publica detrás de un proxy con certificado (IIS, nginx o Caddy) con
  `DJANGO_DEBUG=False`; la visión acepta el certificado interno con `BIOVIGIA_VERIFICAR_TLS`.
- **Los horarios reales de los turnos**, pendientes con el cliente
  (`BIOVIGIA_TURNOS` en `servidor/biovigia/settings.py`).
- **La tarea programada de depuración** (`python manage.py depurar_evidencia`): además
  se ejecuta sola, como mucho una vez por hora, cuando alguien abre el tablero.

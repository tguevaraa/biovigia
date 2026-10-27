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

## Estructura

```
biovigia/
├── servidor/        Django + DRF — Darlyn (backend) y Cristofer (pantallas)
├── vision/          Servicio de visión — Francisco
├── datos/           Videos, imágenes y anotaciones — Tommy y Ezequiel
├── herramientas/    Simulador de eventos y utilidades
└── docs/            Contrato de la API, montaje de la escena y bitácora
```

## Documentos que hay que leer antes de escribir código

| Documento | Para quién |
|---|---|
| `docs/contrato-api.md` | **Todos.** Es el acuerdo que permite trabajar en paralelo. |
| `docs/escena-montaje.md` | Tommy y Ezequiel, antes de grabar. |
| `docs/prueba-aceptacion.md` | Todos, para saber cuándo terminamos. |

---

## Arranque

```bash
git clone <url-del-repositorio>
cd biovigia
python -m venv .venv

# Linux o macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate
```

Según en qué bloque trabajes:

```bash
pip install -r requirements-servidor.txt   # Darlyn y Cristofer
pip install -r requirements-vision.txt     # Francisco y Ezequiel
```

Levantar el servidor:

```bash
cd servidor
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Llenar el tablero con datos de prueba, sin necesidad de cámara:

```bash
python herramientas/simulador.py --n 20
```

### Base de datos

El MVP arranca con **SQLite** para no perder tiempo instalando PostgreSQL en cinco
máquinas. El cambio a PostgreSQL es una línea en `settings.py` y se hace antes de la
demo (BVIA-33). El ORM de Django es lo que permite diferirlo.

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

## Lo que **no** entra en el MVP

Exportación a CSV y PDF, acciones correctivas, gestión de usuarios desde la interfaz,
parámetros desde la interfaz, las pantallas PAN-07 a PAN-11, CloudWatch, el modo oscuro,
el dispositivo de borde y el clasificador de scikit-learn.

Nada de eso se borra del tablero: se queda en el backlog y se retoma después. El campo
`rasgos` se guarda desde el primer evento precisamente para poder entrenar ese
clasificador más adelante con datos reales.

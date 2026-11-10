/* BioVigIA · editor gráfico de zonas (PAN-09, RF-01, RNF-20).
 * Los puntos se guardan normalizados entre 0 y 1 sobre el fotograma de 640 × 480.
 */
(function () {
  "use strict";
  const cfg = window.BV_ZONAS;
  const lienzo = document.getElementById("z-lienzo");
  const ctx = lienzo.getContext("2d");
  const W = lienzo.width, H = lienzo.height;
  const COLORES = { rojo: "#E35D53", comun: "#E6EAEF" };
  const ETIQUETAS = { rojo: "Recipiente rojo", comun: "Recipiente común" };

  const zonas = JSON.parse(document.getElementById("z-datos").textContent);
  const camara = JSON.parse(document.getElementById("z-camara").textContent);
  let tipo = document.querySelector("input[name=z-tipo]:checked").value;
  let trazo = []; // puntos del polígono en edición (normalizados)
  let fondo = null;

  function mensaje(texto, clase) {
    const caja = document.getElementById("z-mensaje");
    const icono = { "bv-ok": "check-circle", "bv-bad": "x-octagon", "bv-warn": "exclamation-triangle" }[clase] || "info-circle";
    caja.innerHTML = "";
    if (!texto) return;
    const div = document.createElement("div");
    div.className = "bv-aviso " + clase;
    div.innerHTML = '<i class="bi bi-' + icono + '" aria-hidden="true"></i><div></div>';
    div.lastElementChild.textContent = texto;
    caja.appendChild(div);
  }

  function actualizarEstados() {
    for (const t of ["rojo", "comun"]) {
      const el = document.querySelector('[data-estado="' + t + '"]');
      if (t === tipo && trazo.length) el.textContent = trazo.length + " punto" + (trazo.length === 1 ? "" : "s");
      else el.textContent = zonas[t] ? "Guardado" : "Sin trazar";
    }
    document.querySelectorAll(".bv-opcion-zona").forEach((op) => {
      op.classList.toggle("activa", op.dataset.tipo === tipo);
    });
    const z = zonas[tipo];
    document.getElementById("z-ultima").textContent = z && z.actualizado_en
      ? "Última modificación: " + new Date(z.actualizado_en).toLocaleString("es-EC") + (z.actualizado_por ? " por " + z.actualizado_por : "")
      : "";
  }

  function poligono(puntos, color, cerrado, punteado) {
    if (!puntos.length) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(punteado ? [6, 5] : []);
    ctx.beginPath();
    puntos.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
    if (cerrado) {
      ctx.closePath();
      ctx.fillStyle = color + "33";
      ctx.fill();
    }
    ctx.stroke();
    ctx.setLineDash([]);
    for (const [x, y] of puntos) {
      ctx.beginPath();
      ctx.arc(x * W, y * H, 5, 0, Math.PI * 2);
      ctx.fillStyle = "#fff";
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.stroke();
    }
    ctx.restore();
  }

  function etiqueta(puntos, texto, color) {
    if (!puntos.length) return;
    const x = Math.min(...puntos.map((p) => p[0])) * W;
    const y = Math.min(...puntos.map((p) => p[1])) * H;
    ctx.font = "600 12px system-ui, sans-serif";
    const ancho = ctx.measureText(texto).width + 10;
    ctx.fillStyle = "rgba(16,21,27,.85)";
    ctx.fillRect(x, Math.max(0, y - 22), ancho, 18);
    ctx.fillStyle = color;
    ctx.fillText(texto, x + 5, Math.max(13, y - 9));
  }

  function dibujar() {
    ctx.clearRect(0, 0, W, H);
    if (fondo) {
      ctx.drawImage(fondo, 0, 0, W, H);
    } else {
      ctx.fillStyle = "#2B323B";
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#A5ACB5";
      ctx.font = "14px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Sin fotograma de referencia.", W / 2, H / 2 - 10);
      ctx.fillText("Envíalo desde el servicio de visión: python -m vision --enviar-referencia", W / 2, H / 2 + 14);
      ctx.textAlign = "start";
    }
    for (const t of ["rojo", "comun"]) {
      if (t === tipo && trazo.length) continue;
      if (zonas[t]) {
        poligono(zonas[t].puntos, COLORES[t], true, false);
        etiqueta(zonas[t].puntos, ETIQUETAS[t] + " · " + zonas[t].puntos.length + " puntos", COLORES[t]);
      }
    }
    if (trazo.length) {
      poligono(trazo, COLORES[tipo], trazo.length >= 3, true);
      etiqueta(trazo, ETIQUETAS[tipo] + " · trazando", COLORES[tipo]);
    }
    actualizarEstados();
  }

  function punto(ev) {
    const r = lienzo.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width));
    const y = Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height));
    return [Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000];
  }

  lienzo.addEventListener("pointerdown", (ev) => {
    if (trazo.length >= 20) return mensaje("Máximo 20 puntos por polígono.", "bv-warn");
    trazo.push(punto(ev));
    mensaje("");
    dibujar();
  });
  document.getElementById("z-deshacer").addEventListener("click", () => { trazo.pop(); dibujar(); });
  document.getElementById("z-limpiar").addEventListener("click", () => { trazo = []; dibujar(); });
  document.getElementById("z-trazar").addEventListener("click", () => {
    trazo = [];
    mensaje("Haz clic sobre la boca del " + ETIQUETAS[tipo].toLowerCase() + " para añadir puntos.", "bv-off");
    dibujar();
  });
  document.querySelectorAll("input[name=z-tipo]").forEach((radio) => radio.addEventListener("change", () => {
    tipo = radio.value;
    trazo = [];
    mensaje("");
    dibujar();
  }));

  document.getElementById("z-guardar").addEventListener("click", async () => {
    if (!camara.cumple) {
      return mensaje("La fuente de video no cumple el mínimo de " + camara.fps_minimo + " fps; no se puede guardar.", "bv-warn");
    }
    if (trazo.length < 3) {
      return mensaje("Traza al menos 3 puntos sobre la boca del recipiente antes de guardar.", "bv-warn");
    }
    const boton = document.getElementById("z-guardar");
    boton.disabled = true;
    try {
      const r = await BioVigIA.api(cfg.urlZonas, {
        method: "PUT", body: JSON.stringify({ zonas: [{ tipo, puntos: trazo }] }),
      });
      if (r.ok) {
        Object.assign(zonas, r.datos.zonas);
        trazo = [];
        mensaje("Zona del " + ETIQUETAS[tipo].toLowerCase() + " guardada. El servicio de visión la aplica en su próxima consulta.", "bv-ok");
      } else {
        mensaje((r.datos && r.datos.detalle) || "No se pudo guardar la zona.", r.estado === 409 ? "bv-warn" : "bv-bad");
      }
    } catch (e) {
      mensaje("Sin conexión con el servidor. La zona no se guardó; vuelve a intentarlo.", "bv-bad");
    } finally {
      boton.disabled = !camara.cumple;
      dibujar();
    }
  });

  if (camara.referencia_disponible) {
    const img = new Image();
    img.onload = () => { fondo = img; dibujar(); };
    img.onerror = () => dibujar();
    img.src = cfg.urlReferencia + "?t=" + Date.now();
  }
  dibujar();
})();

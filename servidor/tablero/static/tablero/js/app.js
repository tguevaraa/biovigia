/* BioVigIA · utilidades del cliente web (C4). Sin lógica de negocio: solo presentación. */
(function () {
  "use strict";

  function cookie(nombre) {
    const par = document.cookie.split("; ").find((c) => c.startsWith(nombre + "="));
    return par ? decodeURIComponent(par.split("=")[1]) : "";
  }

  /** fetch con la cookie de sesión y el token CSRF de Django. */
  async function api(url, opciones = {}) {
    const cabeceras = Object.assign({ Accept: "application/json" }, opciones.headers || {});
    if (opciones.body && !(opciones.body instanceof FormData)) {
      cabeceras["Content-Type"] = "application/json";
    }
    if (opciones.method && opciones.method !== "GET") {
      cabeceras["X-CSRFToken"] = cookie("csrftoken");
    }
    const resp = await fetch(url, Object.assign({}, opciones, {
      headers: cabeceras, credentials: "same-origin",
    }));
    let datos = null;
    const tipo = resp.headers.get("Content-Type") || "";
    if (tipo.includes("application/json")) {
      datos = await resp.json();
    }
    return { ok: resp.ok, estado: resp.status, datos };
  }

  /**
   * Patrón Observer en la interfaz: consulta la API cada `intervalo` ms y, si la huella
   * calculada por `huella(datos)` cambia, recarga la vista para reflejar el nuevo estado.
   * Se pausa cuando la pestaña no está visible.
   */
  function observar(url, huella, intervalo = 10000) {
    let previa = null;
    async function revisar() {
      if (document.hidden) return;
      try {
        const r = await api(url);
        if (!r.ok || !r.datos) return;
        const actual = huella(r.datos);
        if (previa !== null && actual !== previa) {
          window.location.reload();
          return;
        }
        previa = actual;
        const marca = document.getElementById("bv-actualizado");
        if (marca) {
          marca.textContent = new Date().toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit", hour12: false });
        }
      } catch (e) {
        /* Sin red: se reintenta en el siguiente ciclo, sin molestar al usuario. */
      }
    }
    revisar();
    setInterval(revisar, intervalo);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) revisar(); });
  }

  /** Evita el doble envío y avisa si se perdió la red antes de enviar (recambio no guardado). */
  function protegerEnvio(idFormulario, idAviso) {
    const form = document.getElementById(idFormulario);
    if (!form) return;
    form.addEventListener("submit", (ev) => {
      if (!navigator.onLine) {
        ev.preventDefault();
        document.getElementById(idAviso)?.classList.remove("d-none");
        return;
      }
      form.querySelectorAll("button[type=submit]").forEach((b) => {
        b.disabled = true;
        b.textContent = "Guardando…";
      });
    });
  }

  window.BioVigIA = { api, observar, protegerEnvio, cookie };
})();

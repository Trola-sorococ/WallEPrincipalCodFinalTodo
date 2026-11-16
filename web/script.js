/* =========================================================
   COBOT Wall-E · Interactividad de la página
   ========================================================= */
(function () {
  "use strict";

  // Marca que JS está activo (las animaciones de aparición dependen de esto)
  document.documentElement.classList.add("js");

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ---------- Menú móvil ---------- */
  const navToggle = $("#navToggle");
  const navLinks = $("#navLinks");

  function cerrarMenu() {
    navLinks.classList.remove("open");
    navToggle.setAttribute("aria-expanded", "false");
  }

  navToggle.addEventListener("click", () => {
    const abierto = navLinks.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(abierto));
  });
  $$("a", navLinks).forEach((a) => a.addEventListener("click", cerrarMenu));

  /* ---------- Sección activa en el menú ---------- */
  const secciones = $$("main section[id]");
  const enlaces = new Map($$("a", navLinks).map((a) => [a.getAttribute("href").slice(1), a]));

  if ("IntersectionObserver" in window) {
    const spy = new IntersectionObserver(
      (entradas) => {
        entradas.forEach((e) => {
          if (e.isIntersecting) {
            enlaces.forEach((a) => a.classList.remove("active"));
            const link = enlaces.get(e.target.id);
            if (link) link.classList.add("active");
          }
        });
      },
      { rootMargin: "-45% 0px -50% 0px" }
    );
    secciones.forEach((s) => spy.observe(s));

    /* ---------- Aparición al hacer scroll ---------- */
    const revelar = new IntersectionObserver(
      (entradas, obs) => {
        entradas.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("visible");
            obs.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    $$(".reveal").forEach((el) => revelar.observe(el));
  } else {
    $$(".reveal").forEach((el) => el.classList.add("visible"));
  }

  /* ---------- Botón volver arriba ---------- */
  const toTop = $("#toTop");
  window.addEventListener(
    "scroll",
    () => { toTop.hidden = window.scrollY < 600; },
    { passive: true }
  );
  toTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

  /* ---------- Filtro y búsqueda del pinout ---------- */
  const pinRows = $$("#pinTable tbody tr");
  const pinSearch = $("#pinSearch");
  const pinEmpty = $("#pinEmpty");
  let filtroActual = "all";

  function filtrarPines() {
    const texto = pinSearch.value.trim().toLowerCase();
    let visibles = 0;
    pinRows.forEach((fila) => {
      const grupos = fila.dataset.group.split(" ");
      const coincideGrupo = filtroActual === "all" || grupos.includes(filtroActual);
      const coincideTexto = fila.textContent.toLowerCase().includes(texto);
      const mostrar = coincideGrupo && coincideTexto;
      fila.hidden = !mostrar;
      if (mostrar) visibles++;
    });
    pinEmpty.hidden = visibles > 0;
  }

  $$("#pinFilters .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $$("#pinFilters .chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      filtroActual = chip.dataset.filter;
      filtrarPines();
    });
  });
  pinSearch.addEventListener("input", filtrarPines);

  /* ---------- Búsqueda en la tabla de comandos ---------- */
  const cmdRows = $$("#cmdTable tbody tr");
  const cmdSearch = $("#cmdSearch");
  const cmdEmpty = $("#cmdEmpty");

  cmdSearch.addEventListener("input", () => {
    const texto = cmdSearch.value.trim().toLowerCase();
    let visibles = 0;
    cmdRows.forEach((fila) => {
      const mostrar = fila.textContent.toLowerCase().includes(texto);
      fila.hidden = !mostrar;
      if (mostrar) visibles++;
    });
    cmdEmpty.hidden = visibles > 0;
  });

  /* ---------- Copiar código ---------- */
  $$(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const destino = $(btn.dataset.copyTarget);
      if (!destino) return;
      try {
        await navigator.clipboard.writeText(destino.textContent);
        btn.textContent = "¡Copiado!";
      } catch {
        // Respaldo para abrir el archivo directamente (file://) sin permisos del portapapeles
        const rango = document.createRange();
        rango.selectNodeContents(destino);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(rango);
        btn.textContent = "Selecciona y copia (Ctrl+C)";
      }
      setTimeout(() => { btn.textContent = "Copiar"; }, 1800);
    });
  });

  /* ---------- Simulador del robot ---------- */
  const LIMITE_FRENO = 20; // cm, igual que en la interfaz de Python

  const estado = { traccion: null, brazos: "N", cabeza: "3" };
  let distancia = 120;

  const el = {
    consola: $("#simConsole"),
    trac: $("#stTrac"),
    brazos: $("#stBrazos"),
    cabeza: $("#stCabeza"),
    sensor: $("#stSensor"),
    slider: $("#simDist"),
    salida: $("#simDistOut"),
    barra: $("#distFill"),
  };

  const TRACCION = {
    F: "Avanzando",
    B: "Retrocediendo",
    L: "Girando a la izquierda",
    R: "Girando a la derecha",
  };

  const BRAZOS = {
    U: "Subiendo ambos",
    D: "Bajando ambos",
    N: "90° (detenidos)",
  };

  const CABEZA = {
    "1": "Girando a un lado",
    "2": "Girando al otro lado",
    "3": "Centro",
  };

  function log(texto, clase) {
    const primero = el.consola.querySelector(".muted");
    if (primero) primero.remove();
    const p = document.createElement("p");
    if (clase) p.className = clase;
    p.textContent = texto;
    el.consola.appendChild(p);
    // Evita que la consola crezca sin límite
    while (el.consola.children.length > 60) el.consola.removeChild(el.consola.firstChild);
    el.consola.scrollTop = el.consola.scrollHeight;
  }

  function pintarEstado() {
    el.trac.textContent = estado.traccion ? TRACCION[estado.traccion] : "Detenido";
    el.trac.className = "badge " + (estado.traccion ? "run" : "");
    el.brazos.textContent = BRAZOS[estado.brazos];
    el.brazos.className = "badge " + (estado.brazos === "N" ? "" : "run");
    el.cabeza.textContent = CABEZA[estado.cabeza];
    el.cabeza.className = "badge " + (estado.cabeza === "3" ? "" : "run");
  }

  function pintarSensor() {
    el.salida.textContent = distancia + " cm";
    el.barra.style.width = Math.min(100, (distancia / 200) * 100) + "%";
    const cerca = distancia <= LIMITE_FRENO;
    el.barra.classList.toggle("danger", cerca);
    el.sensor.textContent = cerca ? "Obstáculo" : "Libre";
    el.sensor.className = "badge " + (cerca ? "bad" : "ok");
  }

  function enviarComando(cmd) {
    log("> " + cmd, "tx");

    if (TRACCION[cmd]) {
      // Igual que la interfaz real: no se arranca hacia adelante con un obstáculo delante
      if (cmd === "F" && distancia <= LIMITE_FRENO) {
        log("< Bloqueado: obstáculo a " + distancia + " cm", "warn");
        return;
      }
      estado.traccion = cmd;
      log("< " + TRACCION[cmd] + " (PWM 220)", "rx");
    } else if (cmd === "S") {
      estado.traccion = null;
      log("< Motores detenidos", "rx");
    } else if (BRAZOS[cmd]) {
      estado.brazos = cmd;
      log("< Brazos: " + BRAZOS[cmd], "rx");
    } else if (CABEZA[cmd]) {
      estado.cabeza = cmd;
      log("< Cabeza: " + CABEZA[cmd], "rx");
    } else if (cmd === "X") {
      estado.traccion = null;
      estado.brazos = "N";
      estado.cabeza = "3";
      log("< Todo detenido", "rx");
    }
    pintarEstado();
  }

  $$("#simButtons button").forEach((btn) => {
    btn.addEventListener("click", () => enviarComando(btn.dataset.cmd));
  });

  el.slider.addEventListener("input", () => {
    distancia = Number(el.slider.value);
    pintarSensor();
    // Freno de emergencia: solo si el robot avanza (la marcha atrás queda libre)
    if (distancia <= LIMITE_FRENO && estado.traccion === "F") {
      log("! DIST:" + distancia + " → freno de emergencia", "warn");
      estado.traccion = null;
      log("> S", "tx");
      log("< Motores detenidos", "rx");
      pintarEstado();
    }
  });

  $("#simClear").addEventListener("click", () => {
    el.consola.innerHTML = '<p class="muted">// Consola limpia</p>';
  });

  pintarEstado();
  pintarSensor();

  /* ---------- Año del pie de página ---------- */
  $("#year").textContent = new Date().getFullYear();
})();

"use strict";
/**
 * index.js — App de Gestión de Stock (Frontend)
 * ------------------------------------------------------------
 * Propósito: manejar UI, escaneo de códigos de barras, modales y
 * comunicación con endpoints Django.
 *
 * Cambios clave en este refactor:
 *  - Estructura por secciones y utilidades reutilizables (DOM, fetch, UI).
 *  - Reemplazo de .then() por async/await para mayor legibilidad.
 *  - Validaciones defensivas de elementos del DOM.
 *  - Consolidación de listeners duplicados y setInterval con early exit.
 *  - Exposición explícita en window de funciones que se usan desde HTML.
 *  - Correcciones menores (p. ej., endpoint sin "/" inicial en actualizarProductosEscaneados).
 *
 * Posibles mejoras (TODO):
 *  - Centralizar estado en un Store (Patrón Observer) para evitar múltiples fetches.
 *  - Reemplazar polling (setInterval) por Server‑Sent Events/WebSocket o señales de UI.
 *  - Manejo offline más robusto (Background Sync; colas de requests;
 *    cache de catálogo/stock en IndexedDB).
 *  - Migrar chips de bocas/orígenes a <button type="button"> con
 *    event delegation en lugar de onClick inline.
 *  - Tipado con JSDoc/TypeScript para prevenir errores de datos.
 *  - Unificar render de tablas (general vs grupos) con una sola función
 *    parametrizable.
 *  - Accesibilidad (focus management en modales; ARIA attributes).
 */

/********************
 * 1) Estado global *
 ********************/
let productosEscaneados = [];                // Lista corriente de productos en sesión
let modo = "";                               // "ingresar" | "retirar"
let modalAbierta = false;                    // Controla si el escaneo está habilitado
let faltantesSet = new Set();                // Productos sin stock suficiente (solo retiro)
let tipoActualCrear = "";                    // Contexto para modal de creación (retirar|ingresar)
let bocaSeleccionada = "";                   // Última boca/origen seleccionado
let deferredPrompt = null;                   // PWA install prompt

/********************************
 * 2) Constantes y selectores   *
 ********************************/
const SELECTORS = {
  installBtn: "#installBtn",
  codigoScanner: "#codigoScanner",
  contenedorIngresar: "#contenedor-input-ingresar",
  contenedorRetirar: "#contenedor-input-retirar",
  stockTable: "#stockTable",
  vistaGrupos: "#vistaGrupos",
  modalPrefix: "#modal-", // se concatena con tipo
  modalContentPrefix: "#modal-content-", // idem
  modalConfirmacion: "#modal-confirmacion",
  mensajeConfirmacion: "#mensajeConfirmacion",
  modalDenegado: "#modal-denegado",
  mensajeDenegado: "#mensajeDenegado",
  botonVistaGrupos: "#botonVistaGrupos",
  botonVistaGeneral: "#botonVistaGeneral",
  botonRetiro: "#retirar",
  sidebar: "#sidebar",
  overlay: "#overlay",
  menuBtn: "#menu-btn",
  listaRetiro: "#listaEscaneadosRetiro",
  listaIngreso: "#listaEscaneadosIngreso",
  mensajeError: "#mensaje-error",
};

// Endpoints (centralizados)
const API = {
  reiniciarLista: "/api/reiniciar_lista_temporal/",
  obtenerTemporales: "/api/obtener_productos_temporales/",
  procesarCodigo: "/api/procesar_codigo/",
  confirmarIngreso: "/api/confirmar_codigos/",
  confirmarRetiro: "/api/confirmar_retiro/",
  obtenerStock: "/api/obtener_stock/",
  stockDetallado: "/api/stock_detallado/",
  obtenerCodigos: "/api/obtener_codigos", // corregido (agregar "/" si falta en backend)
  obtenerBocas: "/api/obtener_bocas_salida/",
  obtenerOrigenes: "/api/obtener_origenes/",
  crearBoca: "/api/crear_boca_salida/",
  crearOrigen: "/api/crear_origen/",
  eliminarBoca: "/api/eliminar_boca_salida/",
  eliminarOrigen: "/api/eliminar_origen/",
  eliminarTemporal: "/api/eliminar_producto_temporal/",
};

/********************************
 * 3) Utilidades generales      *
 ********************************/
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function byId(id) {
  return document.getElementById(id);
}

function ensureEl(sel) {
  const el = $(sel);
  if (!el) console.warn(`Elemento no encontrado: ${sel}`);
  return el;
}

function setVisible(el, visible) {
  if (!el) return;
  el.style.display = visible ? "block" : "none";
}

function setDisabled(el, disabled) {
  if (!el) return;
  el.disabled = !!disabled;
}

async function getJSON(url) {
  const res = await fetch(url);
  // defensivo: intentar JSON, y si falla, retornar objeto con error
  try { return await res.json(); } catch { return { error: true, status: res.status }; }
}

async function postJSON(url, bodyObj) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bodyObj ?? {}),
  });
  try { return await res.json(); } catch { return { error: true, status: res.status }; }
}

/********************************
 * 4) Service Worker / PWA      *
 ********************************/
(function setupPWA() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js")
      .then((reg) => console.log("✅ Service Worker registrado:", reg))
      .catch((err) => console.error("❌ Error registrando Service Worker:", err));
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    const installBtn = ensureEl(SELECTORS.installBtn);
    if (installBtn) installBtn.style.display = "block";
  });

  const installBtn = ensureEl(SELECTORS.installBtn);
  if (installBtn) {
    installBtn.addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      const choiceResult = await deferredPrompt.userChoice;
      if (choiceResult?.outcome === "accepted") {
        console.log("✅ El usuario instaló la app");
      }
      deferredPrompt = null;
    });
  }
})();

/********************************
 * 5) Escaneo y modales         *
 ********************************/
const codigoScanner = ensureEl(SELECTORS.codigoScanner);
if (codigoScanner) {
  setDisabled(codigoScanner, true);
}

function activarInputEscaneo() {
  if (!codigoScanner) return;
  setDisabled(codigoScanner, false);
  codigoScanner.focus();
}

function desactivarInputEscaneo() {
  if (!codigoScanner) return;
  setDisabled(codigoScanner, true);
  codigoScanner.blur();
}

// Entrada por Enter cuando la modal está abierta
if (codigoScanner) {
  codigoScanner.addEventListener("keydown", async (event) => {
    // Nota: Hay dos listeners iguales en el código original; consolidado en uno.
    if (!modalAbierta) {
      console.warn("⛔ Escaneo bloqueado porque la modal está cerrada.");
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const codigo = codigoScanner.value.trim();
      if (codigo.length === 13 && !isNaN(Number(codigo))) {
        console.log("📡 Código escaneado:", codigo);
        await procesarCodigoEscaneado(codigo);
        codigoScanner.value = "";
      } else {
        console.warn("⚠️ Código inválido:", codigo);
      }
    }
  });
}

async function abrirModal(tipo) {
  modo = tipo; // "ingresar" | "retirar"
  modalAbierta = true;
  console.log(`📢 Modal abierta: ${tipo}`);

  if (!codigoScanner) return;
  codigoScanner.style.visibility = "visible";

  const contenedorIngresar = ensureEl(SELECTORS.contenedorIngresar);
  const contenedorRetirar = ensureEl(SELECTORS.contenedorRetirar);
  if (tipo === "ingresar") {
    contenedorIngresar?.appendChild(codigoScanner);
  } else {
    contenedorRetirar?.appendChild(codigoScanner);
  }

  // Cargar chips (bocas/orígenes) con preferencia por "Portofino"
  const inputContainer = byId(`contenedor-boca-${tipo}`);
  const endpoint = tipo === "retirar" ? API.obtenerBocas : API.obtenerOrigenes;
  try {
    const data = await getJSON(endpoint);
    if (data?.lista?.length > 0) {
      const lista = data.lista.map((n) => String(n).trim());
      const preferida = "Portofino";
      const listaOrdenada = [
        ...lista.filter((n) => n === preferida),
        ...lista.filter((n) => n !== preferida),
      ];
      const primera = listaOrdenada[0] ?? "";
      if (inputContainer) {
        inputContainer.innerHTML = `
          <label>${tipo === "retirar" ? "Boca de salida" : "Ingresar a"}:</label>
          <div id="bocas-container-${tipo}" class="bocas-container">
            ${listaOrdenada
              .map((nombre, i) => {
                const clase = i === 0 ? "boca-btn seleccionada" : "boca-btn";
                // Nota: usamos onclick inline por compatibilidad con plantilla existente
                return `<button class="${clase}" data-nombre="${nombre}" onclick="seleccionarBoca('${nombre.replace(/'/g, "\\'")}', '${tipo}')">📍 ${nombre}</button>`;
              })
              .join("")}
          </div>
          <input type="hidden" id="input-boca-${tipo}" value="${primera}">
        `;
      }
    }
  } catch (e) {
    console.error("Error cargando bocas/orígenes:", e);
  }

  // Reiniciar lista temporal en backend + limpiar UI
  try {
    await postJSON(API.reiniciarLista);
    productosEscaneados = [];
    actualizarListaEscaneados(modo, []);
  } catch (e) {
    console.error("Error al reiniciar la lista:", e);
  }

  // Mostrar modal y activar escaneo
  const modal = byId(`modal-${tipo}`);
  if (!modal) {
    console.error(`⚠️ No se encontró la modal: modal-${tipo}`);
    return;
  }
  const modalContent = byId(`modal-content-${tipo}`);
  modal.style.display = "block";
  modal.classList.remove("fade-out");
  modalContent?.classList.remove("zoom-out");

  activarInputEscaneo();
  await obtenerProductosEscaneados();
  setTimeout(() => codigoScanner?.focus(), 100);
}

function cerrarModal(tipo) {
  modalAbierta = false;
  console.log(`❌ Modal cerrada: ${tipo}`);

  const modal = byId(`modal-${tipo}`);
  const modalContent = byId(`modal-content-${tipo}`);
  if (!modal) {
    console.error(`⚠️ No se encontró la modal: modal-${tipo}`);
    return;
  }
  modalContent?.classList.add("zoom-out");
  modal.classList.add("fade-out");
  setTimeout(() => {
    modal.style.display = "none";
    modal.classList.remove("fade-out");
    modalContent?.classList.remove("zoom-out");
    desactivarInputEscaneo();
  }, 300);
}

function cerrarModalDenegado() {
  const m = ensureEl(SELECTORS.modalDenegado);
  m?.classList.add("zoom-out");
  m?.classList.add("fade-out");
  setTimeout(() => {
    if (!m) return;
    m.style.display = "none";
    m.classList.remove("fade-out");
    m.classList.remove("zoom-out");
  }, 300);
}

function cerrarModalConfirmacion() {
  const m = ensureEl(SELECTORS.modalConfirmacion);
  m?.classList.add("zoom-out");
  m?.classList.add("fade-out");
  setTimeout(() => {
    if (!m) return;
    m.style.display = "none";
    m.classList.remove("fade-out");
    m.classList.remove("zoom-out");
    location.reload();
  }, 300);
}

/*******************************************
 * 6) Productos escaneados / listas / UI   *
 *******************************************/
async function obtenerProductosEscaneados() {
  if (!modalAbierta) return; // Evitar fetch cuando la modal está cerrada
  try {
    const data = await getJSON(API.obtenerTemporales);
    productosEscaneados = Array.isArray(data?.productos) ? data.productos : [];
    actualizarListaEscaneados(modo, productosEscaneados);
  } catch (e) {
    console.error("Error al obtener productos escaneados:", e);
  }
}

function actualizarListaEscaneados(modalTipo, lista) {
  if (!modalAbierta) return;
  const listaEl = modalTipo === "retirar" ? $(SELECTORS.listaRetiro) : $(SELECTORS.listaIngreso);
  if (!listaEl) {
    console.error("⚠️ No se encontró la lista del modal:", modalTipo);
    return;
  }
  listaEl.innerHTML = "";
  if (!Array.isArray(lista) || lista.length === 0) {
    listaEl.innerHTML = `
      <li style="opacity:.7; font-style: italic;">
        No hay productos escaneados todavía.
      </li>
    `;
    return;
  }

  for (const producto of lista) {
    const li = document.createElement("li");
    li.textContent = `Balde: ${producto.nombre}, Peso: ${producto.peso}g, Código: ${producto.codigo_barras}`;

    const btn = document.createElement("button");
    btn.classList.add("btnEliminar");
    btn.textContent = "❌";
    btn.style.cursor = "pointer";
    btn.addEventListener("click", () => eliminarProductoEscaneado(producto.plu, modalTipo));

    li.appendChild(btn);
    listaEl.appendChild(li);
  }

  if (modalTipo === "retirar") {
    validarStockParaRetiro();
  }
}

async function eliminarProductoEscaneado(plu, modalTipo) {
  try {
    const data = await postJSON(API.eliminarTemporal, { plu });
    if (data?.success) {
      console.log("🗑 Producto eliminado de la sesión:", plu);
      await obtenerProductosEscaneados();
    } else {
      console.error("❌ Error al eliminar producto:", data?.error);
    }
  } catch (e) {
    console.error("⚠️ Error eliminando producto:", e);
  }
}

async function actualizarTotales() {
  try {
    const data = await getJSON(API.obtenerStock); // mismo que usa actualizarTablas()
    if (Array.isArray(data?.stock)) {
      const totalBaldes = data.stock.reduce((acc, it) => acc + Number(it.cantidad || 0), 0);
      const elBaldes = document.getElementById('totalBaldes');
      if (elBaldes) elBaldes.textContent = String(totalBaldes);
    }

    // Si tenés /api/totales/ o devolvés total_kilos en obtener_stock, actualizá también:
    // const tot = await getJSON('/api/totales/');
    // if (tot?.total_kilos != null) document.getElementById('totalKilos').textContent = tot.total_kilos;
  } catch (e) {
    console.error('No se pudieron actualizar los totales', e);
  }
}


async function actualizarTablas() {
  console.log("🔄 Actualizando tabla general de stock...");
  const tablaStock = ensureEl(SELECTORS.stockTable);
  if (!tablaStock) return;
  try {
    const data = await getJSON(API.obtenerStock);
    if (!Array.isArray(data?.stock)) {
      console.error("❌ Respuesta sin 'stock' válido.");
      return;
    }
    const encabezado = `
      <thead>
        <tr>
          <th>Producto</th>
          <th>Cantidad de Baldes</th>
        </tr>
      </thead>`;

    let body = "<tbody>";
    if (data.stock.length === 0) {
      body += `
        <tr>
          <td colspan="2" style="text-align:center; font-style:italic; color:gray;">No hay productos en stock.</td>
        </tr>`;
    } else {
      for (const item of data.stock) {
        const rowClass = item.cantidad < item.stock_minimo ? "resaltar-bajo-stock" : "";
        body += `<tr class="${rowClass}"><td>${item.nombre}</td><td>${item.cantidad}</td></tr>`;
      }
    }
    body += "</tbody>";
    tablaStock.innerHTML = encabezado + body;
    console.log("✅ Tabla de stock actualizada.");
  } catch (e) {
    console.error("❌ Error al actualizar la tabla de stock:", e);
  }
}

async function actualizarTablasGrupos() {
  try {
    const json = await getJSON(API.stockDetallado); // tu endpoint /api/stock_detallado/

    // Normalización defensiva: intentamos encontrar el array de items
    let items = [];
    if (Array.isArray(json)) {
      items = json;
    } else if (Array.isArray(json?.data)) {
      items = json.data;
    } else if (Array.isArray(json?.stock)) {
      items = json.stock;
    } else if (Array.isArray(json?.items)) {
      items = json.items;
    } else if (json?.grupos && typeof json.grupos === "object") {
      // Si el backend ya envía por grupos, renderizamos directo y retornamos
      renderizarGruposDesdeObjeto(json.grupos);
      return;
    } else {
      console.warn("⚠️ /api/stock_detallado/ no devolvió un array reconocible. Respuesta:", json);
      items = [];
    }

    // Asegurar que cada item tenga los campos esperados (nombre, grupo, cantidad, etc.)
    // Ajustá los nombres a lo que te entregue tu API.
    const seguros = items.map(it => ({
      nombre: it.nombre ?? it.producto ?? "",
      grupo:  (it.grupo ?? "").toLowerCase(),
      cantidad: Number(it.cantidad ?? it.cant ?? 0),
      // otros campos si los usás...
    }));

    // Agrupar por grupo
    const porGrupo = seguros.reduce((acc, it) => {
      const g = it.grupo || "otros";
      if (!acc[g]) acc[g] = [];
      acc[g].push(it);
      return acc;
    }, {});

    renderizarGruposDesdeObjeto(porGrupo);
  } catch (err) {
    console.error("❌ actualizarTablasGrupos() falló:", err);
  }
}

// Render que llena cada <tbody id="*-body"> según el objeto { grupo: [items...] }
function renderizarGruposDesdeObjeto(porGrupo) {
  // Mapa de ids de tbody por clave de grupo (ajustá las claves si tu backend usa otras)
  const mapIds = {
    jarabe: "jarabe-body",
    chocolates: "chocolates-body",
    dulces: "dulces-body",
    blanca: "blanca-body",
    neutra: "neutra-body",
    zambayon: "zambayon-body",
    oleosa: "oleosa-body",
    otros: "otros-body" // por si querés agregar un contenedor “otros”
  };

  // Limpiar todos los tbody conocidos
  Object.values(mapIds).forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = "";
  });

  // Volcar filas
  Object.entries(porGrupo).forEach(([grupo, lista]) => {
    const tbodyId = mapIds[grupo] || mapIds.otros;
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    const rows = (Array.isArray(lista) ? lista : []).map(it => {
      const nombre = (it.nombre ?? "").toString();
      const cantidad = Number(it.cantidad ?? 0);
      return `<tr><td>${escapeHtml(nombre)}</td><td>${cantidad}</td></tr>`;
    }).join("");

    tbody.innerHTML = rows;
  });
}

// Utilidad mínima para escapar HTML en nombres
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}


/*******************************************
 * 7) Comunicación con backend (acciones)  *
 *******************************************/
async function procesarCodigoEscaneado(codigo) {
  try {
    const data = await postJSON(API.procesarCodigo, { codigo });
    if (data?.error) {
      console.error("❌ Error procesando código:", data.error);
    } else {
      console.log("✔ Código procesado con éxito:", data);
      await actualizarProductosEscaneados();
      await validarStockParaRetiro();
    }
  } catch (e) {
    console.error("⚠️ Error en la petición de procesar código:", e);
  }
}

async function actualizarProductosEscaneados() {
  try {
    const data = await getJSON(API.obtenerCodigos);
    if (!Array.isArray(data?.productos)) {
      console.error("❌ API obtener_codigos sin array 'productos'.");
      return;
    }
    productosEscaneados = data.productos;
  } catch (e) {
    console.error("Error al obtener productos escaneados:", e);
  }
}

async function confirmarAgregarProductos() {
  console.log("📢 Intentando confirmar productos. Lista actual:", productosEscaneados);
  if (!productosEscaneados || productosEscaneados.length === 0) {
    mostrarModalDenegado("No hay productos escaneados para agregar.");
    return;
  }
  const boca = byId("input-boca-ingresar")?.value?.trim();
  if (!boca) {
    mostrarModalDenegado("Por favor, seleccioná un origen.");
    return;
  }
  const payload = {
    origen: boca,
    productos: productosEscaneados.map(p => ({
      plu: p.plu,
      peso: p.peso,
      // 👇 clave nueva que enviamos al backend
      codigo_barras: p.codigo_barras
    }))
  };
  try {
    const data = await postJSON(API.confirmarIngreso, payload);
    if (data?.error) {
      console.error("❌ Error al confirmar productos:", data.error);
      mostrarModalDenegado(data.error ?? "No se pudo ingresar el producto");
    } else {
      console.log("✅ Productos agregados correctamente.");
      mostrarModalConfirmacion(data.message ?? "Productos agregados");
      cerrarModal("ingresar");
      productosEscaneados = [];
      //await Promise.all([actualizarTablas(), actualizarTablasGrupos()]);
      location.reload()
      actualizarTotales();
    }
  } catch (e) {
    console.error("⚠️ Error al agregar productos:", e);
  }
}

async function confirmarRetirarProductos() {
  const ok = await validarStockParaRetiro();
  const faltantes = Array.from(faltantesSet).join("\n");
  if (!ok) {
    mostrarModalDenegado(
      `No se puede continuar con el retiro porque hay productos sin stock:\n${faltantes}`
    );
    return;
  }
  if (!productosEscaneados?.length) {
    mostrarModalDenegado("No hay productos escaneados para retirar.");
    return;
  }
  const boca = byId("input-boca-retirar")?.value?.trim();
  if (!boca) {
    mostrarModalDenegado("Por favor, seleccioná una boca de salida.");
    return;
  }
  const payload = {
    destino: boca,
    productos: productosEscaneados.map(p => ({
      plu: p.plu,
      // para retiro basta con el código; si querés mandar peso también no molesta
      codigo_barras: p.codigo_barras
    }))
  };
  try {
    const data = await postJSON(API.confirmarRetiro, payload);
    if (data?.error) {
      console.error("❌ Error al retirar productos:", data.error);
      mostrarModalDenegado(data.error ?? "No se pudo retirar el producto");
      return;
    }
    console.log("✅ Productos retirados correctamente.");
    mostrarModalConfirmacion(data.message ?? "Productos retirados");
    cerrarModal("retirar");
    productosEscaneados = [];
    //await Promise.all([actualizarTablas(), actualizarTablasGrupos()]);
    location.reload()
    actualizarTotales();
  } catch (e) {
    console.error("❌ Error al retirar productos:", e);
  }
}

/*******************************************
 * 8) Validación de stock (retiro)         *
 *******************************************/
async function validarStockParaRetiro() {
  try {
    const dataStock = await getJSON(API.stockDetallado);
    const dataEscaneados = await getJSON(API.obtenerTemporales);
    if (!Array.isArray(dataStock?.stock_detallado) || !Array.isArray(dataEscaneados?.productos)) {
      console.error("Error al obtener stock o productos escaneados.");
      return false;
    }
    const stockProductos = dataStock.stock_detallado;
    const listaEscaneados = dataEscaneados.productos;

    faltantesSet.clear();
    let hayStockInsuficiente = false;

    for (const prod of listaEscaneados) {
      const pStock = stockProductos.find((p) => p.nombre === prod.nombre);
      if (pStock) {
        const cantDisponible = pStock.cantidad;
        const cantRetirar = listaEscaneados.filter((p) => p.nombre === prod.nombre).length;
        if (cantDisponible < cantRetirar) {
          faltantesSet.add(`${prod.nombre} ❗`);
          hayStockInsuficiente = true;
          const fila = document.querySelector(`.producto-fila[data-nombre="${prod.nombre}"]`);
          fila?.classList.add("sin-stock");
        }
      }
    }

    const botonRetiro = ensureEl(SELECTORS.botonRetiro);
    const mensajeError = ensureEl(SELECTORS.mensajeError);

    if (hayStockInsuficiente) {
      if (mensajeError) {
        mensajeError.innerText = "⚠️ Algunos productos no tienen stock suficiente.";
        mensajeError.style.display = "block";
      }
      setDisabled(botonRetiro, true);
      return false;
    } else {
      if (mensajeError) mensajeError.style.display = "none";
      setDisabled(botonRetiro, false);
      return true;
    }
  } catch (e) {
    console.error("Error validando stock:", e);
    return false;
  }
}

/*******************************************
 * 9) UI: modales de feedback              *
 *******************************************/
function mostrarModalConfirmacion(mensaje) {
  const modal = ensureEl(SELECTORS.modalConfirmacion);
  const texto = ensureEl(SELECTORS.mensajeConfirmacion);
  if (!modal || !texto) return;
  texto.innerText = mensaje;
  modal.style.display = "block";
}

function mostrarModalDenegado(mensaje) {
  const modal = ensureEl(SELECTORS.modalDenegado);
  const texto = ensureEl(SELECTORS.mensajeDenegado);
  if (!modal || !texto) return;
  texto.innerText = mensaje;
  modal.style.display = "block";
}

/*******************************************
 * 10) Vista: grupos / general             *
 *******************************************/
const GRUPOS = {
  jarabe: ["LIMON", "FRUTILLA AL AGUA", "DURAZNO"],
  chocolates: [
    "CHOCOLATE",
    "CHOCOLAE BLOCK",
    "CH. CABSHA",
    "CHOCO DUBAI",
    "AMARGO",
    "CH. ALMENDRAS",
    "CH. PASAS RHUM",
    "CHOCOLAT PORTOFINO",
    "CHOCOLATE INTENSO",
    "CHOCOLAT DEBILIDAD",
    "CHOC. BLANCO",
    "ROCHER",
    "TOFFEE BLANCO",
  ],
  dulces: [
    "DCE LECHE",
    "DCE. LECHE NUEZ",
    "DCE. GRANIZADO",
    "SUPER DCE LECHE",
    "DCE. VAUQUITA",
    "D. LECHE PORTOFINO",
    "DCE. LECHE COOKIES",
    "BASE DULCE LECHE",
    "CHOCOTORTA",
  ],
  blanca: [
    "AMERICANA",
    "VAINILLA",
    "TRAMONTANA",
    "GRANIZADO",
    "MENTA GRANIZADA",
    "CREMA FLAN",
    "FRUTOS DEL BOSQUE",
    "CREMA DEL CIELO",
    "PANNACOTA",
    "MASCARPONE",
    "CAPUCCINO",
    "OREO",
    "SNIKERS",
  ],
  neutra: [
    "CEREZA",
    "PISTACHO",
    "FRUTILLA CREMA",
    "BANANA SPLIT",
    "MARACUYA",
    "ANANA AL CHANTILLY",
    "FRAMBUESA C/ CHOCO",
    "KINOTOS AL WHISKY",
    "DURAZNOS AL OPORTO",
    "MANZANA VERDE",
    "LEMON PIE",
    "LIMON C/MARACUYA",
    "FRAMBUESA C/CHOCO",
    "HAVANETA LIMON",
  ],
  zambayon: ["SAMBAYON", "SAMBAYON PORTOFINO"],
  oleosa: ["ALMENDRADO", "CREMA RUSA", "MARROC"],
};

function mostrarVistaGrupos() {
  console.log("🔄 Mostrando vista de grupos...");
  const tabla = ensureEl(SELECTORS.stockTable);
  const vg = ensureEl(SELECTORS.vistaGrupos);
  if (!tabla || !vg) return;

  tabla.classList.add("fade-out");
  setTimeout(() => {
    tabla.style.display = "none";
    tabla.classList.remove("fade-out");
    vg.style.display = "flex";
    requestAnimationFrame(() => {
      vg.classList.add("fade-in");
      setTimeout(() => vg.classList.remove("fade-in"), 300);
    });
  }, 300);

  const gruposBody = {
    jarabe: byId("jarabe-body"),
    chocolates: byId("chocolates-body"),
    dulces: byId("dulces-body"),
    blanca: byId("blanca-body"),
    neutra: byId("neutra-body"),
    zambayon: byId("zambayon-body"),
    oleosa: byId("oleosa-body"),
  };
  Object.values(gruposBody).forEach((el) => el && (el.innerHTML = ""));

  $(`#stockTable tbody`)?.querySelectorAll("tr").forEach((row) => {
    const nombre = row.cells[0].textContent.trim().toUpperCase();
    const cantidad = row.cells[1].textContent.trim();

    let grupoAsignado = "otros";
    for (const [grupo, productos] of Object.entries(GRUPOS)) {
      if (productos.includes(nombre)) { grupoAsignado = grupo; break; }
    }

    const nueva = document.createElement("tr");
    nueva.innerHTML = `<td>${nombre}</td><td>${cantidad}</td>`;
    if (row.classList.contains("resaltar-bajo-stock")) {
      nueva.classList.add("resaltar-bajo-stock");
    }
    gruposBody[grupoAsignado]?.appendChild(nueva);
  });
}

function mostrarVistaGeneral() {
  console.log("🔄 Mostrando vista general...");
  const tabla = ensureEl(SELECTORS.stockTable);
  const vg = ensureEl(SELECTORS.vistaGrupos);
  if (!tabla || !vg) return;

  vg.classList.add("fade-out");
  setTimeout(() => {
    vg.style.display = "none";
    vg.classList.remove("fade-out");
    tabla.style.display = "table";
    requestAnimationFrame(() => {
      tabla.classList.add("fade-in");
      setTimeout(() => tabla.classList.remove("fade-in"), 300);
    });
  }, 300);
}

/*******************************************
 * 11) Menú lateral / overlay              *
 *******************************************/
function openMenu() {
  ensureEl(SELECTORS.sidebar)?.classList.add("open");
  ensureEl(SELECTORS.overlay)?.classList.add("active");
}

function closeMenu() {
  ensureEl(SELECTORS.sidebar)?.classList.remove("open");
  ensureEl(SELECTORS.overlay)?.classList.remove("active");
}

/*******************************************
 * 12) Bootstrapping de eventos            *
 *******************************************/
document.addEventListener("DOMContentLoaded", () => {
  console.log("📢 DOM completamente cargado.");

  // Botones de cambio de vista
  ensureEl(SELECTORS.botonVistaGrupos)?.addEventListener("click", mostrarVistaGrupos);
  ensureEl(SELECTORS.botonVistaGeneral)?.addEventListener("click", mostrarVistaGeneral);

  // Menú lateral
  ensureEl(SELECTORS.menuBtn)?.addEventListener("click", openMenu);
  ensureEl(SELECTORS.closeBtn)?.addEventListener("click", closeMenu);
  ensureEl(SELECTORS.overlay)?.addEventListener("click", closeMenu);

  // Polling suave: solo hace trabajo si la modal está abierta
  setInterval(() => { if (modalAbierta) obtenerProductosEscaneados(); }, 500);
});

/*******************************************
 * 13) Exponer funciones globales          *
 *******************************************/
// Algunas funciones son invocadas desde atributos onclick en HTML existente.
Object.assign(window, {
  abrirModal,
  cerrarModal,
  cerrarModalDenegado,
  cerrarModalConfirmacion,
  confirmarAgregarProductos,
  confirmarRetirarProductos,
  mostrarVistaGrupos,
  mostrarVistaGeneral,
  openMenu,
  closeMenu,
});

// seleccionarBoca expuesta (usa dataset + input hidden)
function seleccionarBoca(nombre, tipo) {
  $(`#bocas-container-${tipo}`)?.querySelectorAll(".boca-btn").forEach((btn) => btn.classList.remove("seleccionada"));
  const boton = document.querySelector(`#bocas-container-${tipo} .boca-btn[data-nombre="${CSS.escape(nombre)}"]`);
  boton?.classList.add("seleccionada");
  const hidden = byId(`input-boca-${tipo}`);
  if (hidden) hidden.value = nombre;
  bocaSeleccionada = nombre;
}
window.seleccionarBoca = seleccionarBoca;

/*******************************************
 * 14) Modales de creación / chips         *
 *******************************************/
async function abrirModalCrearBoca(tipo) {
  tipoActualCrear = tipo;
  const input = byId("nombreNuevaBoca");
  const error = byId("errorCrearBoca");
  if (input) input.value = "";
  if (error) error.style.display = "none";

  const titulo = byId("tituloCrearBoca");
  if (titulo) titulo.textContent = tipo === "retirar" ? "Crear nueva boca de salida" : "Crear nuevo origen";

  const modal = byId("modalCrearBoca");
  if (modal) modal.style.display = "block";

  const endpoint = tipo === "retirar" ? API.obtenerBocas : API.obtenerOrigenes;
  const data = await getJSON(endpoint);
  const container = byId("chipsExistentes");
  if (!container) return;
  container.innerHTML = "";
  if (Array.isArray(data?.lista) && data.lista.length > 0) {
    for (const nombre of data.lista) {
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.innerHTML = `📍 ${String(nombre).trim()} <span class="close-chip" onclick="eliminarBocaDesdeModal('${String(nombre).trim().replace(/'/g, "\\'")}')">&times;</span>`;
      container.appendChild(chip);
    }
  } else {
    container.innerHTML = "<p style='font-style: italic;'>No hay opciones creadas.</p>";
  }
}
window.abrirModalCrearBoca = abrirModalCrearBoca;

function cerrarModalCrearBoca() {
  const modal = byId("modalCrearBoca");
  if (modal) modal.style.display = "none";
}
window.cerrarModalCrearBoca = cerrarModalCrearBoca;

async function confirmarCreacionBoca() {
  const nombre = byId("nombreNuevaBoca")?.value?.trim();
  const error = byId("errorCrearBoca");
  if (!nombre) {
    if (error) {
      error.textContent = "El nombre no puede estar vacío.";
      error.style.display = "block";
    }
    return;
  }
  const endpoint = tipoActualCrear === "retirar" ? API.crearBoca : API.crearOrigen;
  const data = await postJSON(endpoint, { nombre });
  if (data?.success) {
    abrirModalCrearBoca(tipoActualCrear); // recargar chips
  } else if (error) {
    error.textContent = data?.error || "Error al crear.";
    error.style.display = "block";
  }
}
window.confirmarCreacionBoca = confirmarCreacionBoca;

async function eliminarBocaDesdeModal(nombre) {
  if (!confirm(`¿Eliminar "${nombre}"?`)) return;
  const endpoint = tipoActualCrear === "retirar" ? API.eliminarBoca : API.eliminarOrigen;
  const data = await postJSON(endpoint, { nombre });
  if (data?.success) {
    abrirModalCrearBoca(tipoActualCrear); // recargar tras eliminar
  } else {
    alert("❌ Error al eliminar: " + (data?.error || "Desconocido"));
  }
}
window.eliminarBocaDesdeModal = eliminarBocaDesdeModal;

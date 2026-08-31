"use strict";
/**
 * index.js – App de Gestión de Stock (Frontend)
 * ------------------------------------------------------------
 * VERSIÓN OPTIMIZADA con:
 * - Sistema de notificaciones Toast
 * - Loading states en botones
 * - Feedback visual al escanear
 * - Polling reducido (2 segundos)
 * - Código refactorizado y comentado
 */

/********************
 * 1) Estado global *
 ********************/
let productosEscaneados = [];
let modo = "";
let modalAbierta = false;
let faltantesSet = new Set();
let tipoActualCrear = "";
let bocaSeleccionada = "";
let deferredPrompt = null;

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
  modalPrefix: "#modal-",
  modalContentPrefix: "#modal-content-",
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
  listaDevolucion: "#listaEscaneadosDevolucion",
  mensajeError: "#mensaje-error",
};

const API = {
  reiniciarLista: "/api/reiniciar_lista_temporal/",
  obtenerTemporales: "/api/obtener_productos_temporales/",
  procesarCodigo: "/api/procesar_codigo/",
  confirmarIngreso: "/api/confirmar_codigos/",
  confirmarRetiro: "/api/confirmar_retiro/",
  obtenerStock: "/api/obtener_stock/",
  stockDetallado: "/api/stock_detallado/",
  obtenerCodigos: "/api/obtener_codigos/",
  obtenerBocas: "/api/obtener_bocas_salida/",
  obtenerOrigenes: "/api/obtener_origenes/",
  crearBoca: "/api/crear_boca_salida/",
  crearOrigen: "/api/crear_origen/",
  eliminarBoca: "/api/eliminar_boca_salida/",
  eliminarOrigen: "/api/eliminar_origen/",
  eliminarTemporal: "/api/eliminar_producto_temporal/",
  imprimirStockTotal: "/api/print_stock_total/",
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
  try { return await res.json(); } 
  catch { return { error: true, status: res.status }; }
}

async function postJSON(url, bodyObj) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bodyObj ?? {}),
  });
  try { return await res.json(); } 
  catch { return { error: true, status: res.status }; }
}

/********************************
 * 4) Sistema Toast             *
 ********************************/
const ToastSystem = {
  container: null,
  
  init() {
    this.container = document.getElementById('toast-container');
    if (!this.container) {
      console.warn('Toast container no encontrado. Creando...');
      this.container = document.createElement('div');
      this.container.id = 'toast-container';
      this.container.className = 'toast-container';
      document.body.appendChild(this.container);
    }
  },
  
  show(message, type = 'success', duration = 3000, title = null) {
    if (!this.container) this.init();
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icon = this.getIcon(type);
    const toastTitle = title || this.getDefaultTitle(type);
    
    toast.innerHTML = `
      <div class="toast-icon">${icon}</div>
      <div class="toast-content">
        <div class="toast-title">${toastTitle}</div>
        <div class="toast-message">${message}</div>
      </div>
      <button class="toast-close" aria-label="Cerrar">×</button>
    `;
    
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => this.remove(toast));
    
    this.container.appendChild(toast);
    
    if (duration > 0) {
      setTimeout(() => this.remove(toast), duration);
    }
    
    return toast;
  },
  
  remove(toast) {
    if (!toast || !toast.parentElement) return;
    
    toast.classList.add('removing');
    setTimeout(() => {
      if (toast.parentElement) {
        toast.remove();
      }
    }, 300);
  },
  
  getIcon(type) {
    const icons = {
      success: '✓',
      error: '✕',
      warning: '⚠',
      info: 'ℹ'
    };
    return icons[type] || icons.info;
  },
  
  getDefaultTitle(type) {
    const titles = {
      success: 'Éxito',
      error: 'Error',
      warning: 'Advertencia',
      info: 'Información'
    };
    return titles[type] || 'Notificación';
  },
  
  success(message, title = null, duration = 3000) {
    return this.show(message, 'success', duration, title);
  },
  
  error(message, title = null, duration = 4000) {
    return this.show(message, 'error', duration, title);
  },
  
  warning(message, title = null, duration = 3500) {
    return this.show(message, 'warning', duration, title);
  },
  
  info(message, title = null, duration = 3000) {
    return this.show(message, 'info', duration, title);
  }
};

window.Toast = ToastSystem;

/********************************
 * 4.5) Sistema ConfirmDialog   *
 ********************************/
const ConfirmDialog = {
  modal: null,
  titleEl: null,
  messageEl: null,
  acceptBtn: null,
  cancelBtn: null,
  dialogEl: null,
  
  init() {
    this.modal = document.getElementById('confirm-dialog');
    this.titleEl = document.getElementById('confirm-title');
    this.messageEl = document.getElementById('confirm-message');
    this.acceptBtn = document.getElementById('confirm-accept');
    this.cancelBtn = document.getElementById('confirm-cancel');
    this.dialogEl = this.modal?.querySelector('.confirm-dialog');
    
    if (!this.modal) {
      console.warn('Confirm dialog no encontrado. Creando...');
      this.createModal();
    }
  },
  
  createModal() {
    const modal = document.createElement('div');
    modal.id = 'confirm-dialog';
    modal.className = 'modal';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content confirm-dialog">
        <div class="confirm-icon">⚠️</div>
        <h3 id="confirm-title" class="confirm-title">Confirmar acción</h3>
        <p id="confirm-message" class="confirm-message">¿Estás seguro?</p>
        <div class="confirm-buttons">
          <button id="confirm-cancel" class="btn-secondary">Cancelar</button>
          <button id="confirm-accept" class="btn-primary">Aceptar</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    
    this.modal = modal;
    this.titleEl = document.getElementById('confirm-title');
    this.messageEl = document.getElementById('confirm-message');
    this.acceptBtn = document.getElementById('confirm-accept');
    this.cancelBtn = document.getElementById('confirm-cancel');
    this.dialogEl = modal.querySelector('.confirm-dialog');
  },
  
  show(options = {}) {
    if (!this.modal) this.init();
    
    const {
      title = 'Confirmar acción',
      message = '¿Estás seguro?',
      icon = '⚠️',
      acceptText = 'Aceptar',
      cancelText = 'Cancelar',
      type = 'warning',
    } = options;
    
    return new Promise((resolve) => {
      this.titleEl.textContent = title;
      this.messageEl.textContent = message;
      this.acceptBtn.textContent = acceptText;
      this.cancelBtn.textContent = cancelText;
      
      const iconEl = this.dialogEl.querySelector('.confirm-icon');
      if (iconEl) iconEl.textContent = icon;
      
      this.dialogEl.className = `modal-content confirm-dialog ${type}`;
      
      this.modal.style.display = 'flex';
      
      const handleAccept = () => {
        this.hide();
        resolve(true);
      };
      
      const handleCancel = () => {
        this.hide();
        resolve(false);
      };
      
      const newAcceptBtn = this.acceptBtn.cloneNode(true);
      const newCancelBtn = this.cancelBtn.cloneNode(true);
      this.acceptBtn.replaceWith(newAcceptBtn);
      this.cancelBtn.replaceWith(newCancelBtn);
      this.acceptBtn = newAcceptBtn;
      this.cancelBtn = newCancelBtn;
      
      this.acceptBtn.addEventListener('click', handleAccept);
      this.cancelBtn.addEventListener('click', handleCancel);
      
      const handleEsc = (e) => {
        if (e.key === 'Escape') {
          handleCancel();
          document.removeEventListener('keydown', handleEsc);
        }
      };
      document.addEventListener('keydown', handleEsc);
      
      this.modal.addEventListener('click', (e) => {
        if (e.target === this.modal) {
          handleCancel();
        }
      }, { once: true });
      
      setTimeout(() => this.acceptBtn.focus(), 100);
    });
  },
  
  hide() {
    if (!this.modal) return;
    this.modal.style.display = 'none';
  },
  
  async danger(message, title = 'Advertencia') {
    return this.show({
      title,
      message,
      icon: '⚠️',
      type: 'danger',
      acceptText: 'Eliminar',
      cancelText: 'Cancelar'
    });
  },
  
  async warning(message, title = 'Confirmar') {
    return this.show({
      title,
      message,
      icon: '⚠️',
      type: 'warning',
      acceptText: 'Continuar',
      cancelText: 'Cancelar'
    });
  },
  
  async info(message, title = 'Información') {
    return this.show({
      title,
      message,
      icon: 'ℹ️',
      type: 'info',
      acceptText: 'Aceptar',
      cancelText: 'Cancelar'
    });
  }
};

window.ConfirmDialog = ConfirmDialog;

/********************************
 * 5) Service Worker / PWA      *
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
 * 6) Escaneo y modales         *
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

if (codigoScanner) {
  codigoScanner.addEventListener("keydown", async (event) => {
    if (!modalAbierta && !modoDevolucion) {
      console.warn("⛔ Escaneo bloqueado porque la modal está cerrada.");
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const codigo = codigoScanner.value.trim();
      if (codigo.length === 13 && !isNaN(Number(codigo))) {
        console.log("📡 Código escaneado:", codigo);
        if (modoDevolucion) {
          await procesarCodigoDevolucion(codigo);
        } else {
          await procesarCodigoEscaneado(codigo);
        }
        codigoScanner.value = "";
      } else {
        console.warn("⚠️ Código inválido:", codigo);
        Toast.warning("Código de barras inválido");
      }
    }
  });
}

async function abrirModal(tipo) {
  modo = tipo;
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
    Toast.error("Error al cargar opciones");
  }

  try {
    await postJSON(API.reiniciarLista);
    productosEscaneados = [];
    actualizarListaEscaneados(modo, []);
  } catch (e) {
    console.error("Error al reiniciar la lista:", e);
  }

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
 * 7) Productos escaneados / listas / UI   *
 *******************************************/
async function obtenerProductosEscaneados() {
  if (!modalAbierta && !modoDevolucion) return;
  try {
    const data = await getJSON(API.obtenerTemporales);
    productosEscaneados = Array.isArray(data?.productos) ? data.productos : [];
    actualizarListaEscaneados(modoDevolucion ? "devolucion" : modo, productosEscaneados);
  } catch (e) {
    console.error("Error al obtener productos escaneados:", e);
  }
}

function actualizarListaEscaneados(modalTipo, lista) {
  if (!modalAbierta && !modoDevolucion) return;
  let listaEl;
  if (modalTipo === "retirar") listaEl = $(SELECTORS.listaRetiro);
  else if (modalTipo === "devolucion") listaEl = $(SELECTORS.listaDevolucion);
  else listaEl = $(SELECTORS.listaIngreso);
  if (!listaEl) {
    console.error("⚠️ No se encontró la lista del modal:", modalTipo);
    return;
  }

  const cantidad = Array.isArray(lista) ? lista.length : 0;
  const contadorId = modalTipo === "retirar" ? "contadorRetiro" : modalTipo === "devolucion" ? "contadorDevolucion" : "contadorIngreso";
  const contadorEl = document.getElementById(contadorId);
  console.log(contadorEl);
  if (contadorEl) {
    contadorEl.textContent = `${cantidad}`;
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
    btn.textContent = "✕";
    btn.style.cursor = "pointer";
    btn.addEventListener("click", () => eliminarProductoEscaneado(producto.codigo_barras, modalTipo));

    li.appendChild(btn);
    listaEl.appendChild(li);
  }

  if (modalTipo === "retirar") {
    validarStockParaRetiro();
  }
}

async function eliminarProductoEscaneado(codigoBarras, modalTipo) {
  try {
    const data = await postJSON(API.eliminarTemporal, { codigo_barras: codigoBarras });
    if (data?.success) {
      console.log("🗑️ Producto eliminado de la sesión:", plu);
      Toast.info("Producto eliminado");
      await obtenerProductosEscaneados();
    } else {
      console.error("❌ Error al eliminar producto:", data?.error);
      Toast.error("No se pudo eliminar el producto");
    }
  } catch (e) {
    console.error("⚠️ Error eliminando producto:", e);
    Toast.error("Error al eliminar producto");
  }
}

async function actualizarTablaStock() {
  try {
    const data = await getJSON(API.obtenerStock);
    if (!Array.isArray(data?.stock)) return;

    // Actualizar tabla
    const tablaStock = ensureEl(SELECTORS.stockTable);
    if (tablaStock) {
      const encabezado = `<thead><tr><th>Producto</th><th>Cantidad de Baldes</th></tr></thead>`;
      let body = "<tbody>";
      if (data.stock.length === 0) {
        body += `<tr><td colspan="2" style="text-align:center;font-style:italic;color:gray;">No hay productos en stock.</td></tr>`;
      } else {
        for (const item of data.stock) {
          const rowClass = item.cantidad < item.stock_minimo ? "resaltar-bajo-stock" : "";
          body += `<tr class="${rowClass}"><td>${item.nombre}</td><td>${item.cantidad}</td></tr>`;
        }
      }
      body += "</tbody>";
      tablaStock.innerHTML = encabezado + body;
    }

    // Actualizar totales generales
    const totalBaldes = data.stock.reduce((acc, it) => acc + Number(it.cantidad || 0), 0);
    const totalKilos  = data.stock.reduce((acc, it) => acc + Number(it.kg_total  || 0), 0);
    const elBaldes = document.getElementById("totalBaldes");
    const elKilos  = document.getElementById("totalKilos");
    if (elBaldes) elBaldes.textContent = String(totalBaldes);
    if (elKilos)  elKilos.textContent  = totalKilos.toFixed(2);

    // Actualizar totales por categoría
    if (data.categorias) {
      const c = data.categorias;
      const upd = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      upd("bHelado",      c.helado.baldes);
      upd("kHelado",      c.helado.kilos.toFixed(2));
      upd("bBarraTorta",  c.barra_torta.baldes);
      upd("kBarraTorta",  c.barra_torta.kilos.toFixed(2));
      upd("bGastronomico",c.gastronomico.baldes);
      upd("kGastronomico",c.gastronomico.kilos.toFixed(2));
    }

  } catch (e) {
    console.error("❌ Error al actualizar tabla de stock:", e);
  }
}

// actualizarTotales ahora delega en actualizarTablaStock (que actualiza tabla + totales juntos)
async function actualizarTotales() {
  await actualizarTablaStock();
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

// Actualizar actualizarTablasGrupos() con skeletons
async function actualizarTablasGrupos() {
  const container = document.getElementById('vistaGrupos');
  if (!container) return;
  
  // ✅ NUEVO: Mostrar skeletons
  SkeletonLoader.show(container, 'grupo', 8);
  
  try {
    const json = await getJSON(API.stockDetallado);
    
    let items = [];
    if (Array.isArray(json)) {
      items = json;
    } else if (Array.isArray(json?.data)) {
      items = json.data;
    } else if (Array.isArray(json?.stock)) {
      items = json.stock;
    }
    
    const seguros = items.map(it => ({
      nombre: it.nombre ?? it.producto ?? "",
      grupo: (it.grupo ?? "").toLowerCase(),
      cantidad: Number(it.cantidad ?? it.cant ?? 0),
    }));
    
    const porGrupo = seguros.reduce((acc, it) => {
      const g = it.grupo || "otros";
      if (!acc[g]) acc[g] = [];
      acc[g].push(it);
      return acc;
    }, {});
    
    // ✅ NUEVO: Ocultar skeletons y mostrar contenido
    SkeletonLoader.hide(container, () => {
      renderizarGruposDesdeObjeto(porGrupo);
    });
    
  } catch (err) {
    console.error("❌ Error:", err);
    SkeletonLoader.hide(container);
    Toast.error("Error al cargar el stock");
  }
}

function renderizarGruposDesdeObjeto(porGrupo) {
  const mapIds = {
    jarabe: "jarabe-body",
    chocolates: "chocolates-body",
    dulces: "dulces-body",
    blanca: "blanca-body",
    neutra: "neutra-body",
    zambayon: "zambayon-body",
    oleosa: "oleosa-body",
    tortas: "tortas-body",
    barras: "barras-body",
    gastronomicos: "gastronomicos-body",
    otros: "otros-body"
  };

  Object.values(mapIds).forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = "";
  });

  Object.entries(porGrupo).forEach(([grupo, lista]) => {
    const tbodyId = mapIds[grupo] || mapIds.otros;
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    const rows = (Array.isArray(lista) ? lista : []).map(it => {
      const nombre = escapeHtml(it.nombre ?? "");
      const cantidad = Number(it.cantidad ?? 0);
      return `<tr><td>${nombre}</td><td>${cantidad}</td></tr>`;
    }).join("");

    tbody.innerHTML = rows;
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/*******************************************
 * 8) Comunicación con backend (acciones)  *
 *******************************************/
async function procesarCodigoEscaneado(codigo) {
  try {
    const data = await postJSON(API.procesarCodigo, { codigo });
    if (data?.error) {
      console.error("❌ Error procesando código:", data.error);
      Toast.error(data.error);
    } else {
      console.log("✅ Código procesado con éxito:", data);
      Toast.success('Producto escaneado', null, 1500);
      
      // Vibración en móvil
      navigator.vibrate?.(50);
      
      await obtenerProductosEscaneados();
      if (modo === "retirar") {
        await validarStockParaRetiro();
      }
    }
  } catch (e) {
    console.error("⚠️ Error en la petición de procesar código:", e);
    Toast.error("Error al procesar el código");
  }
}

async function confirmarAgregarProductos() {
  console.log("📢 Intentando confirmar productos. Lista actual:", productosEscaneados);
  if (!productosEscaneados || productosEscaneados.length === 0) {
    Toast.warning("No hay productos escaneados para agregar");
    return;
  }
  const boca = byId("input-boca-ingresar")?.value?.trim();
  if (!boca) {
    Toast.warning("Por favor, seleccioná un origen");
    return;
  }
  const payload = {
    origen: boca,
    productos: productosEscaneados.map(p => ({
      plu: p.plu,
      peso: p.peso,
      codigo_barras: p.codigo_barras
    }))
  };
  try {
    const res = await fetch(API.confirmarIngreso, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });

    if (res.status === 409) {
      const data409 = await res.json();

      if (data409?.se_puede_forzar) {
        const fecha = data409.fecha_ingreso 
          ? new Date(data409.fecha_ingreso).toLocaleString("es-AR")
          : "-";

        const texto = `
          ${data409.mensaje}
          Producto: <b>${data409.producto ?? "-"}</b>
          Peso previo: <b>${data409.peso_anterior ?? "-"}</b>
          Fecha ingreso: <b>${fecha}</b>
        `;

        mostrarModalDuplicado(texto, () => {
          confirmarAgregarProductosConForzar();
        });

        return;
      }

      Toast.error(data409?.mensaje || "Conflicto detectado");
      return;
    }

    const data = await res.json();

    if (data.success) {
      console.log("✅ Productos agregados correctamente.");
      Toast.success(`${data.productos.length} productos agregados correctamente`);
      cerrarModal("ingresar");
      productosEscaneados = [];
      actualizarTotales();
      actualizarTablaStock();
      //actualizarTablasGrupos();
      location.reload();
    }

  } catch (e) {
    console.error("⚠️ Error al agregar productos:", e);
    Toast.error("No se pudo agregar los productos");
  }
}

async function confirmarAgregarProductosConForzar() {
  const boca = byId("input-boca-ingresar")?.value?.trim();
  const payload = {
    origen: boca,
    force: true,
    productos: productosEscaneados.map(p => ({
      plu: p.plu,
      peso: p.peso,
      codigo_barras: p.codigo_barras
    }))
  };

  const res = await fetch(API.confirmarIngreso, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });

  const data = await res.json();
  Toast.success(data.message ?? "Productos agregados");
  cerrarModal("ingresar");
  productosEscaneados = [];
  actualizarTablaStock(); // actualiza tabla + totales juntos
  //actualizarTablasGrupos();
  location.reload();
}

async function confirmarRetirarProductos() {
  const ok = await validarStockParaRetiro();
  const faltantes = Array.from(faltantesSet).join("\n");
  if (!ok) {
    Toast.error(`No hay stock para: ${faltantes}`);
    return;
  }
  if (!productosEscaneados?.length) {
    Toast.warning("No hay productos escaneados para retirar");
    return;
  }
  const boca = byId("input-boca-retirar")?.value?.trim();
  if (!boca) {
    Toast.warning("Por favor, seleccioná una boca de salida");
    return;
  }
  const payload = {
    destino: boca,
    productos: productosEscaneados.map(p => ({
      plu: p.plu,
      codigo_barras: p.codigo_barras
    }))
  };
  try {
    const data = await postJSON(API.confirmarRetiro, payload);
    if (data?.error) {
      console.error("❌ Error al retirar productos:", data.error);
      Toast.error(data.error ?? "No se pudo retirar el producto");
      return;
    }
    console.log("✅ Productos retirados correctamente.");
    Toast.success(`${data.productos.length} productos retirados correctamente`);
    cerrarModal("retirar");
    productosEscaneados = [];
    actualizarTotales();
    //actualizarTablasGrupos();
    actualizarTablaStock();
    location.reload();
  } catch (e) {
    console.error("❌ Error al retirar productos:", e);
    Toast.error("Error al retirar productos");
  }
}

/*******************************************
 * 9) Validación de stock (retiro)         *
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
          faltantesSet.add(`${prod.nombre} ◀`);
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
 * 10) UI: modales de feedback             *
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

function mostrarModalDuplicado(mensaje, onConfirm) {
  const modal = byId("modal-duplicado");
  const texto = byId("mensajeDuplicado");
  const btnAceptar = byId("btnForzarDuplicado");
  const btnCancelar = byId("btnCancelarDuplicado");

  if (!modal || !texto || !btnAceptar || !btnCancelar) {
    console.error("⚠️ Modal duplicado no encontrada");
    return;
  }

  texto.innerHTML = mensaje;
  modal.style.display = "block";

  btnAceptar.replaceWith(btnAceptar.cloneNode(true));
  btnCancelar.replaceWith(btnCancelar.cloneNode(true));

  const newAceptar = byId("btnForzarDuplicado");
  const newCancelar = byId("btnCancelarDuplicado");

  newAceptar.addEventListener("click", () => {
    modal.style.display = "none";
    if (typeof onConfirm === "function") onConfirm();
  });

  newCancelar.addEventListener("click", () => {
    modal.style.display = "none";
  });
}

/*******************************************
 * 11) CRUD PRODUCTOS                       *
 *******************************************/
async function abrirAdminProductos() {
  const modal = document.getElementById("modal-admin-productos");
  if (modal) modal.style.display = "block";

  try {
    const data = await getJSON("/api/productos/");
    const tbody = document.querySelector("#tabla-productos tbody");
    if (!tbody) return;
    
    tbody.innerHTML = "";

    (data.productos || []).forEach(p => {
      const tr = document.createElement("tr");
      const activo = p.is_activo !== false; // true por defecto si el campo no viene
      tr.style.opacity = activo ? "1" : "0.5";
      tr.innerHTML = `
        <td>${p.plu}</td>
        <td>${p.nombre}</td>
        <td>${p.stock_minimo}</td>
        <td style="text-align:center;">
          <button onclick="togglePluActivo('${p.plu}', ${activo})"
                  title="${activo ? 'Desactivar PLU (ocultar del stock impreso)' : 'Activar PLU (mostrar en stock impreso)'}"
                  style="font-size:1.2rem;background:none;border:none;cursor:pointer;padding:2px 6px;">
            ${activo ? '✅' : '⛔'}
          </button>
        </td>
        <td>
          <button onclick="editarProducto('${p.plu}', '${p.nombre.replace(/'/g, "\\'")}', '${p.stock_minimo}')" class="btn-edit">✏️</button>
          <button onclick="eliminarProducto('${p.plu}')" class="btn-delete">🗑️</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    Toast.error("Error al cargar productos");
  }
}

async function abrirModalCrearProducto() {
  const nombre = prompt("Nombre del producto:");
  if (!nombre) return;

  const plu = prompt("PLU (3 dígitos):");
  const minimo = prompt("Stock mínimo:");

  try {
    const data = await postJSON("/api/crear_producto/", {
      nombre, plu, stock_minimo: minimo
    });

    if (data.success) {
      Toast.success("Producto creado correctamente");
      abrirAdminProductos();
    } else {
      Toast.error(data.error || "Error al crear producto");
    }
  } catch (e) {
    Toast.error("Error al crear producto");
  }
}

async function eliminarProducto(plu) {
  if (!confirm("¿Eliminar el producto permanentemente?")) return;

  try {
    const data = await postJSON("/api/eliminar_producto/", { plu });

    if (data.success) {
      Toast.success("Producto eliminado");
      abrirAdminProductos();
    } else {
      Toast.error(data.error || "No se pudo eliminar");
    }
  } catch (e) {
    Toast.error("Error al eliminar producto");
  }
}

async function editarProducto(plu, nombreActual, minimoActual) {
  const nuevoNombre = prompt("Nuevo nombre del producto:", nombreActual);
  if (nuevoNombre === null) return;

  const nuevoMinimoStr = prompt("Nuevo stock mínimo:", minimoActual ?? "");
  if (nuevoMinimoStr === null) return;

  const payload = {
    plu,
    nombre: nuevoNombre.trim(),
    stock_minimo: nuevoMinimoStr.trim()
  };

  try {
    const data = await postJSON("/api/actualizar_producto/", payload);
    
    if (data.success) {
      Toast.success("Producto actualizado");
      abrirAdminProductos();
    } else {
      Toast.error(data.error || "Error al actualizar");
    }
  } catch (e) {
    Toast.error("Error al actualizar producto");
  }
}

async function togglePluActivo(plu, activoActual) {
  const accion = activoActual ? "desactivar" : "activar";
  if (!confirm(`¿${accion.charAt(0).toUpperCase() + accion.slice(1)} el PLU ${plu}?\n\n` +
    (activoActual
      ? "El sabor dejará de aparecer en la impresión de stock."
      : "El sabor volverá a aparecer en la impresión de stock (aunque tenga 0 baldes).")))
    return;

  try {
    const data = await postJSON("/api/toggle_plu_activo/", { plu });
    if (data.success) {
      Toast.success(data.message || `PLU ${plu} ${data.is_activo ? "activado" : "desactivado"}`);
      abrirAdminProductos();
    } else {
      Toast.error(data.error || "Error al cambiar estado del PLU");
    }
  } catch (e) {
    Toast.error("Error de conexión");
  }
}

function cerrarModalAdminProductos() {
  const modal = byId("modal-admin-productos");
  if (!modal) return;
  modal.classList.add("zoom-out", "fade-out");
  setTimeout(() => {
      modal.style.display = "none";
      modal.classList.remove("fade-out", "zoom-out");
  }, 300);
}

/*******************************************
 * 12) Vista: grupos / general             *
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
    "FLAN MIXTO",
    "FRUTOS DEL BOSQUE",
    "CREMA DEL CIELO",
    "PANNACOTA",
    "MASCARPONE",
    "CHEESE CAKE",
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
  tortas: ["TORTA ALMENDRADO", "TORTA CHOCOTORTA", "TORTA OREO","TORTA PANNACOTTA", "TORTA TRICOLOR" ],
  barras: ["BARRA ALMENDRADO", "BARRA CHOCOTORTA", "BARRA OREO","BARRA PANNACOTTA", "BARRA TRICOLOR" ],
  gastronomico: ["GASTRO"]
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
    tortas: byId("tortas-body"),
    barras: byId("barras-body"),
    gastronomicos: byId("gastronomicos-body"),
  };
  Object.values(gruposBody).forEach((el) => el && (el.innerHTML = ""));

  $(`#stockTable tbody`)?.querySelectorAll("tr").forEach((row) => {
    const nombre = row.cells[0].textContent.trim().toUpperCase();
    const cantidad = row.cells[1].textContent.trim();

    let grupoAsignado = "otros";
    if (nombre.includes("GASTRO")) {
      grupoAsignado = "gastronomicos";
    } else {
      for (const [grupo, productos] of Object.entries(GRUPOS)) {
        if (productos.includes(nombre)) {
          grupoAsignado = grupo;
          break;
        }
      }
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
 * 13) Menú lateral / overlay              *
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
 * 14) Bootstrapping de eventos            *
 *******************************************/
document.addEventListener("DOMContentLoaded", () => {
  console.log("📢 DOM completamente cargado.");

  // Inicializar Toast
  ToastSystem.init();

  // Inicializar ConfirmDialog
  ConfirmDialog.init();

  ensureEl(SELECTORS.botonVistaGrupos)?.addEventListener("click", mostrarVistaGrupos);
  ensureEl(SELECTORS.botonVistaGeneral)?.addEventListener("click", mostrarVistaGeneral);

  ensureEl(SELECTORS.menuBtn)?.addEventListener("click", openMenu);
  ensureEl(SELECTORS.overlay)?.addEventListener("click", closeMenu);

  // ⚡ OPTIMIZACIÓN: Polling reducido a 2 segundos
  setInterval(() => {
    if (modalAbierta) obtenerProductosEscaneados();
  }, 2000);

  // Verificar actualizaciones disponibles (silencioso, no bloquea el inicio)
  setTimeout(checkForUpdate, 3000);
});

/*******************************************
 * Auto-updater                            *
 *******************************************/
async function checkForUpdate() {
  try {
    const res = await fetch("/api/check-update/");
    if (!res.ok) return;
    const data = await res.json();
    if (data.update_available) {
      _mostrarToastActualizacion(data.version, data.download_url, data.release_notes);
    }
  } catch (_) {
    // sin conexión o servidor sin soporte — ignorar silenciosamente
  }
}

function _mostrarToastActualizacion(version, downloadUrl, notes) {
  if (document.getElementById("update-toast")) return;
  const toast = document.createElement("div");
  toast.id = "update-toast";
  toast.style.cssText = [
    "position:fixed", "bottom:24px", "left:50%", "transform:translateX(-50%)",
    "background:#1a73e8", "color:#fff", "padding:14px 18px", "border-radius:12px",
    "z-index:10000", "box-shadow:0 4px 20px rgba(0,0,0,.35)",
    "display:flex", "align-items:center", "gap:12px", "font-size:.9rem",
    "max-width:90vw",
  ].join(";");
  toast.innerHTML = `
    <span>🆕 Nueva versión <strong>v${version}</strong> disponible</span>
    <button id="btn-aplicar-update" style="background:#fff;color:#1a73e8;border:none;border-radius:8px;padding:6px 14px;cursor:pointer;font-weight:600;">Actualizar</button>
    <button onclick="document.getElementById('update-toast').remove()" style="background:transparent;color:#fff;border:none;cursor:pointer;font-size:1.3rem;line-height:1;">×</button>
  `;
  document.body.appendChild(toast);
  document.getElementById("btn-aplicar-update").addEventListener("click", () =>
    _aplicarActualizacion(downloadUrl)
  );
}

async function _aplicarActualizacion(downloadUrl) {
  const btn = document.getElementById("btn-aplicar-update");
  if (btn) { btn.disabled = true; btn.textContent = "Descargando…"; }
  try {
    const res = await fetch("/api/apply-update/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": window.CSRF_TOKEN },
      body: JSON.stringify({ download_url: downloadUrl }),
    });
    const data = await res.json();
    if (data.success) {
      Toast.success("✅ Actualización descargada. La app se cerrará y reabrirá automáticamente en unos segundos.");
    } else {
      Toast.error("❌ Error al actualizar: " + (data.error || "desconocido"));
      if (btn) { btn.disabled = false; btn.textContent = "Reintentar"; }
    }
  } catch (e) {
    Toast.error("❌ Error al actualizar: " + e.message);
    if (btn) { btn.disabled = false; btn.textContent = "Reintentar"; }
  }
}

window.checkForUpdate = checkForUpdate;

/*******************************************
 * Devolución de baldes                    *
 *******************************************/
let modoDevolucion = false;

async function abrirModalDevolucion() {
  modoDevolucion = true;
  await fetch(API.reiniciarLista, { method: "POST", headers: { "X-CSRFToken": window.CSRF_TOKEN } });
  actualizarListaEscaneados("devolucion", []);

  if (codigoScanner) {
    codigoScanner.style.visibility = "visible";
    byId("contenedor-input-devolucion")?.appendChild(codigoScanner);
  }

  await _cargarBocasDevolucion();
  byId("modal-devolucion").style.display = "flex";
  activarInputEscaneo();
}

function cerrarModalDevolucion() {
  modoDevolucion = false;
  desactivarInputEscaneo();
  if (codigoScanner) codigoScanner.style.visibility = "hidden";
  byId("modal-devolucion").style.display = "none";
}

async function _cargarBocasDevolucion() {
  const cont = byId("contenedor-boca-devolucion");
  if (!cont) return;
  try {
    const data = await getJSON(API.obtenerBocas);
    const lista = (data?.lista || []).map(n => String(n).trim());
    if (!lista.length) {
      cont.innerHTML = '<p style="color:#888;font-size:.9em;">No hay bocas de salida cargadas.</p>';
      return;
    }
    cont.innerHTML = `
      <label>Boca de salida de origen:</label>
      <div id="bocas-container-devolucion" class="bocas-container">
        ${lista.map(nombre =>
          `<button class="boca-btn" data-nombre="${nombre}" onclick="seleccionarBoca('${nombre.replace(/'/g, "\\'")}', 'devolucion')">📍 ${nombre}</button>`
        ).join("")}
      </div>
      <input type="hidden" id="input-boca-devolucion" value="">
    `;
  } catch (e) {
    console.error("Error cargando bocas de salida:", e);
  }
}

// Llamada desde el scanner cuando el modal de devolución está abierto
async function procesarCodigoDevolucion(codigo) {
  try {
    const data = await postJSON(API.procesarCodigo, { codigo });
    if (data?.error) { Toast.error(data.error); return; }
    actualizarListaEscaneados("devolucion", data.productos_temporales || []);
  } catch (e) {
    Toast.error("Error al procesar código: " + e.message);
  }
}

async function confirmarDevolucion() {
  const productos = await fetch(API.obtenerTemporales).then(r => r.json()).then(d => d.productos || []);
  if (!productos.length) { Toast.error("No hay baldes en la lista."); return; }

  const origen = byId("input-boca-devolucion")?.value || "";
  if (!origen) { Toast.error("Seleccioná el local de origen."); return; }
  try {
    const res = await fetch("/api/confirmar_devolucion/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": window.CSRF_TOKEN },
      body: JSON.stringify({ productos, origen }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || "Error desconocido");
    Toast.success(data.message);
    cerrarModalDevolucion();
    actualizarTablaStock();
    location.reload();
  } catch (e) {
    Toast.error("Error al confirmar devolución: " + e.message);
  }
}

/*******************************************
 * 15) Exponer funciones globales          *
 *******************************************/
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
  abrirAdminProductos,
  abrirModalCrearProducto,
  eliminarProducto,
  editarProducto,
  togglePluActivo,
  cerrarModalAdminProductos,
  // Devolución
  abrirModalDevolucion,
  cerrarModalDevolucion,
  confirmarDevolucion,
});

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
 * 16) Modales de creación / chips         *
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
  if (!modal) return;
    modal.classList.add("zoom-out", "fade-out");
    setTimeout(() => {
        modal.style.display = "none";
        modal.classList.remove("fade-out", "zoom-out");
    }, 300);
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
  try {
    const data = await postJSON(endpoint, { nombre });
    if (data?.success) {
      Toast.success(`${tipoActualCrear === "retirar" ? "Boca" : "Origen"} creado correctamente`);
      abrirModalCrearBoca(tipoActualCrear);
    } else if (error) {
      error.textContent = data?.error || "Error al crear.";
      error.style.display = "block";
    }
  } catch (e) {
    Toast.error("Error al crear");
  }
}
window.confirmarCreacionBoca = confirmarCreacionBoca;

async function eliminarBocaDesdeModal(nombre) {
  if (!confirm(`¿Eliminar "${nombre}"?`)) return;
  const endpoint = tipoActualCrear === "retirar" ? API.eliminarBoca : API.eliminarOrigen;
  try {
    const data = await postJSON(endpoint, { nombre });
    if (data?.success) {
      Toast.success("Eliminado correctamente");
      abrirModalCrearBoca(tipoActualCrear);
    } else {
      Toast.error(data?.error || "Error al eliminar");
    }
  } catch (e) {
    Toast.error("Error al eliminar");
  }
}
window.eliminarBocaDesdeModal = eliminarBocaDesdeModal;

async function imprimirStockTotal() {
  //if (!confirm("¿Imprimir el stock total en la impresora de tickets?")) return;

  try {
    const data = await postJSON(API.imprimirStockTotal, {});
    if (data.ok) {
      Toast.success("Stock total enviado a la impresora");
    } else {
      Toast.error(data.error || "No se pudo imprimir");
    }
  } catch (e) {
    console.error("Error al imprimir stock total:", e);
    Toast.error("Error al imprimir el stock total");
  }
}
window.imprimirStockTotal = imprimirStockTotal;

/**
 * Sistema de Skeleton Loaders
 */
const SkeletonLoader = {
  /**
   * Crea skeleton para card de grupo
   */
  createGrupoSkeleton() {
    return `
      <div class="skeleton-grupo">
        <div class="skeleton skeleton-title"></div>
        <div class="skeleton-table">
          ${this.createTableRowSkeleton(5)}
        </div>
      </div>
    `;
  },
  
  /**
   * Crea skeleton para fila de tabla
   */
  createTableRowSkeleton(count = 1) {
    return Array(count).fill(0).map(() => `
      <div class="skeleton-table-row">
        <div class="skeleton skeleton-text medium"></div>
        <div class="skeleton skeleton-text short"></div>
      </div>
    `).join('');
  },
  
  /**
   * Crea skeleton para item de movimiento
   */
  createMovItemSkeleton() {
    return `
      <div class="skeleton-mov-item">
        <div class="skeleton-mov-content">
          <div class="skeleton skeleton-text medium"></div>
          <div class="skeleton skeleton-text short"></div>
        </div>
        <div class="skeleton-mov-actions">
          <div class="skeleton skeleton-button"></div>
          <div class="skeleton skeleton-button"></div>
        </div>
      </div>
    `;
  },
  
  /**
   * Crea skeleton para producto escaneado
   */
  createProductoSkeleton() {
    return `
      <div class="skeleton-producto">
        <div class="skeleton skeleton-text long"></div>
      </div>
    `;
  },
  
  /**
   * Muestra skeletons en un container
   * @param {HTMLElement|string} container
   * @param {string} type - 'grupo', 'movimiento', 'producto'
   * @param {number} count - Cantidad de skeletons
   */
  show(container, type = 'grupo', count = 3) {
    const el = typeof container === 'string' 
      ? document.querySelector(container) 
      : container;
      
    if (!el) return;
    
    const skeletons = {
      grupo: this.createGrupoSkeleton,
      movimiento: this.createMovItemSkeleton,
      producto: this.createProductoSkeleton,
      table: () => this.createTableRowSkeleton(5)
    };
    
    const createFn = skeletons[type] || skeletons.grupo;
    
    el.innerHTML = Array(count).fill(0)
      .map(() => createFn.call(this))
      .join('');
    
    el.classList.add('skeletons-active');
  },
  
  /**
   * Oculta skeletons con animación
   * @param {HTMLElement|string} container
   * @param {Function} callback - Se ejecuta después de la animación
   */
  hide(container, callback) {
    const el = typeof container === 'string' 
      ? document.querySelector(container) 
      : container;
      
    if (!el) return;
    
    // Agregar clase de fade out
    el.querySelectorAll('.skeleton-grupo, .skeleton-mov-item, .skeleton-producto')
      .forEach(skeleton => skeleton.classList.add('skeleton-fadeout'));
    
    // Esperar animación y ejecutar callback
    setTimeout(() => {
      el.classList.remove('skeletons-active');
      if (callback) callback();
    }, 300);
  },
  
  /**
   * Reemplaza skeletons con contenido real
   * @param {HTMLElement|string} container
   * @param {string} content - HTML del contenido real
   */
  replace(container, content) {
    this.hide(container, () => {
      const el = typeof container === 'string' 
        ? document.querySelector(container) 
        : container;
      if (el) el.innerHTML = content;
    });
  }
};

// Exponer globalmente
window.SkeletonLoader = SkeletonLoader;

// dashboard.js - Lógica del Dashboard (VERSIÓN CORREGIDA)

/**
 * VARIABLES GLOBALES
 */
let dashboardData = null;
let chartMovimientos = null;
let chartDistribucion = null;
let chartActividad = null;
let autoRefreshInterval = null;
let isAutoRefresh = false;

/**
 * CONFIGURACIÓN
 */
const CONFIG = {
    API_URL: '/api/dashboard/metricas/',
    REFRESH_INTERVAL: 60000, // 60 segundos
    CHART_COLORS: {
        ingreso: 'rgba(40, 167, 69, 0.8)',
        ingresoLight: 'rgba(40, 167, 69, 0.2)',
        retiro: 'rgba(220, 53, 69, 0.8)',
        retiroLight: 'rgba(220, 53, 69, 0.2)',
        primary: 'rgba(0, 86, 179, 0.8)',
        primaryLight: 'rgba(0, 86, 179, 0.2)',
    }
};

// Categoría activa para filtrar el dashboard
let currentCategoria = 'helado';

const CAT_LABELS = {
    helado:       'Helados',
    barra_torta:  'Barras y Tortas',
    gastronomico: 'Gastronómicos',
};

function sincronizarEstadoCats() {
    document.querySelectorAll('.cat-dash-card').forEach(card => {
        card.classList.toggle('active', card.dataset.cat === currentCategoria);
    });
    const label = document.getElementById('cat-filtro-label');
    if (label) {
        if (currentCategoria) {
            label.textContent = `Filtrando por: ${CAT_LABELS[currentCategoria]}  ·  Clic en la card para quitar el filtro`;
            label.style.display = 'block';
        } else {
            label.style.display = 'none';
        }
    }
}

function filtrarPorCategoria(cat) {
    currentCategoria = (currentCategoria === cat) ? null : cat;
    sincronizarEstadoCats();
    cargarDashboard();
}

/**
 * HELPER: Convertir a número seguro
 */
function toNumber(value, defaultValue = 0) {
    const num = parseFloat(value);
    return isNaN(num) ? defaultValue : num;
}


/**
 * CARGA DE DATOS DESDE LA API (RENOMBRADA)
 */
async function cargarDashboard() {
    mostrarLoading(true);

    try {
        const url = currentCategoria
            ? `${CONFIG.API_URL}?categoria=${currentCategoria}`
            : CONFIG.API_URL;
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        dashboardData = await response.json();
        console.log('✅ Datos cargados:', dashboardData);
        
        // Actualizar todos los componentes
        actualizarResumenGeneral();
        actualizarMovimientosHoy();
        actualizarGraficos();
        actualizarTopProductos();
        actualizarAlertas();
        actualizarUltimosMovimientos();
        actualizarProductosSinMovimiento();
        actualizarOrigenesDestinos();
        
        // Mostrar/ocultar resumen del mes según selección
        const selector = document.getElementById('periodo-selector');
        const resumen30 = document.getElementById('resumen-30dias');
        
        if (selector && resumen30) {
            if (selector.value === '30dias') {
                resumen30.style.display = 'block';
                if (dashboardData.resumen_30_dias) {
                    actualizarResumen30Dias(dashboardData.resumen_30_dias);
                }
            } else {
                resumen30.style.display = 'none';
            }
        }
        
        // Actualizar timestamp
        const now = new Date();
        const lastUpdateEl = document.getElementById('lastUpdate');
        if (lastUpdateEl) {
            lastUpdateEl.textContent = now.toLocaleTimeString('es-AR', { 
                hour: '2-digit', 
                minute: '2-digit',
                second: '2-digit'
            });
        }
        
    } catch (error) {
        console.error('❌ Error cargando datos:', error);
        mostrarError('Error al cargar los datos del dashboard');
    } finally {
        mostrarLoading(false);
    }
}

// Alias para compatibilidad
const cargarDatos = cargarDashboard;

/**
 * ACTUALIZAR RESUMEN GENERAL (KPIs)
 */
function actualizarResumenGeneral() {
    const { resumen_general } = dashboardData;
    const c = resumen_general.categorias;

    // Las 4 KPIs usan directamente los valores filtrados que devuelve el backend
    animarNumero('totalBaldes',      resumen_general.total_baldes);
    animarNumero('totalKilos',       resumen_general.total_kilos);
    animarNumero('productosEnStock', resumen_general.productos_en_stock);

    const valorFormateado = resumen_general.valor_inventario.toLocaleString('es-AR', {
        style: 'currency',
        currency: 'ARS',
        minimumFractionDigits: 0
    });
    document.getElementById('valorInventario').textContent = valorFormateado;

    // Actualizar etiquetas de las 4 cards con la categoría activa
    const catLabel = CAT_LABELS[currentCategoria] || '';
    const upd = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    upd('labelBaldes',   `Baldes ${catLabel}`);
    upd('labelKilos',    `Kilos ${catLabel}`);
    upd('labelProductos',`Productos ${catLabel}`);
    upd('labelValor',    `Valor Est. ${catLabel}`);

    // Tarjetas por categoría (siempre datos completos sin filtrar)
    if (c) {
        upd('catHeladoBaldes',    c.helado.baldes);
        upd('catHeladoKilos',     c.helado.kilos.toFixed(2));
        upd('catBarraTortaBaldes',c.barra_torta.baldes);
        upd('catBarraTortaKilos', c.barra_torta.kilos.toFixed(2));
        upd('catGastroBaldes',    c.gastronomico.baldes);
        upd('catGastroKilos',     c.gastronomico.kilos.toFixed(2));
    }
}

/**
 * ACTUALIZAR MOVIMIENTOS DE HOY
 */
function actualizarMovimientosHoy() {
    const { movimientos_hoy } = dashboardData;
    
    document.getElementById('ingresosHoy').textContent = movimientos_hoy.ingresos;
    document.getElementById('kgIngresadosHoy').textContent = toNumber(movimientos_hoy.kg_ingresados).toFixed(2);
    
    document.getElementById('retirosHoy').textContent = movimientos_hoy.retiros;
    document.getElementById('kgRetiradosHoy').textContent = toNumber(movimientos_hoy.kg_retirados).toFixed(2);
    
    actualizarTendencia('trendIngresos', movimientos_hoy.cambio_ingresos);
    actualizarTendencia('trendRetiros', movimientos_hoy.cambio_retiros);
}

/**
 * ACTUALIZAR TENDENCIA
 */
function actualizarTendencia(elementId, cambio) {
    const elemento = document.getElementById(elementId);
    if (!elemento) return;
    
    let icono, clase, texto;
    
    if (cambio > 0) {
        icono = '📈';
        clase = 'trend-positive';
        texto = `+${cambio}% vs ayer`;
    } else if (cambio < 0) {
        icono = '📉';
        clase = 'trend-negative';
        texto = `${cambio}% vs ayer`;
    } else {
        icono = '➡️';
        clase = 'trend-neutral';
        texto = 'Sin cambios vs ayer';
    }
    
    elemento.className = `today-trend ${clase}`;
    elemento.innerHTML = `
        <span class="trend-icon">${icono}</span>
        <span class="trend-text">${texto}</span>
    `;
}

/**
 * ACTUALIZAR GRÁFICOS
 */
function actualizarGraficos() {
    crearGraficoMovimientos();
    crearGraficoDistribucion();
    crearGraficoActividad();
}

/**

/**
 * ACTUALIZAR GRÁFICOS
 */
function actualizarGraficos() {
    crearGraficoMovimientos();
    crearGraficoDistribucion();
    crearGraficoActividad();
}

/**
 * GRÁFICO DE MOVIMIENTOS (con selector de período)
 */
function crearGraficoMovimientos() {
    const ctx = document.getElementById('chartMovimientos');
    if (!ctx) return;
    
    const periodoSelector = document.getElementById('periodo-selector');
    const periodo = periodoSelector ? periodoSelector.value : '7dias';
    
    let labels, dataIngresos, dataRetiros, tooltipData, titulo;
    
    if (periodo === 'custom' && dashboardData.movimientos_custom) {
        // Datos personalizados
        labels = dashboardData.movimientos_custom.map(m => m.fecha);
        dataIngresos = dashboardData.movimientos_custom.map(m => m.ingresos);
        dataRetiros = dashboardData.movimientos_custom.map(m => m.retiros);
        tooltipData = dashboardData.movimientos_custom;
        titulo = 'Movimientos - Período Personalizado';
    } else if (periodo === '30dias' && dashboardData.movimientos_30_dias) {
        // Últimos 30 días
        labels = dashboardData.movimientos_30_dias.map(m => m.fecha);
        dataIngresos = dashboardData.movimientos_30_dias.map(m => m.ingresos);
        dataRetiros = dashboardData.movimientos_30_dias.map(m => m.retiros);
        tooltipData = dashboardData.movimientos_30_dias;
        titulo = 'Movimientos de los Últimos 30 Días';
    } else {
        // Últimos 7 días (por defecto)
        labels = dashboardData.movimientos_7_dias.map(m => m.fecha);
        dataIngresos = dashboardData.movimientos_7_dias.map(m => m.ingresos);
        dataRetiros = dashboardData.movimientos_7_dias.map(m => m.retiros);
        tooltipData = dashboardData.movimientos_7_dias;
        titulo = 'Movimientos Últimos 7 Días';
    }
    
    // Destruir gráfico anterior
    if (chartMovimientos) {
        chartMovimientos.destroy();
    }
    
    chartMovimientos = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Ingresos',
                    data: dataIngresos,
                    borderColor: CONFIG.CHART_COLORS.ingreso,
                    backgroundColor: CONFIG.CHART_COLORS.ingresoLight,
                    tension: 0.4,
                    fill: true,
                    borderWidth: 2
                },
                {
                    label: 'Retiros',
                    data: dataRetiros,
                    borderColor: CONFIG.CHART_COLORS.retiro,
                    backgroundColor: CONFIG.CHART_COLORS.retiroLight,
                    tension: 0.4,
                    fill: true,
                    borderWidth: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                title: {
                    display: true,
                    text: titulo
                },
                tooltip: {
                    callbacks: {
                        afterLabel: function(context) {
                            const index = context.dataIndex;
                            const kg = context.dataset.label === 'Ingresos' 
                                ? tooltipData[index].kg_ingresados
                                : tooltipData[index].kg_retirados;
                            return `${toNumber(kg).toFixed(2)} kg`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1,
                        precision: 0
                    }
                }
            }
        }
    });
}

// Exportar funciones
window.aplicarPeriodoCustom = aplicarPeriodoCustom;

/**
 * GRÁFICO DE DISTRIBUCIÓN
 */
function crearGraficoDistribucion() {
    const ctx = document.getElementById('chartDistribucion');
    if (!ctx) return;
    
    const { distribucion_grupos } = dashboardData;
    
    if (chartDistribucion) {
        chartDistribucion.destroy();
    }
    
    const labels = Object.keys(distribucion_grupos).map(k => 
        k.charAt(0).toUpperCase() + k.slice(1)
    );
    const data = Object.values(distribucion_grupos);
    
    const colores = [
        'rgba(255, 99, 132, 0.8)',
        'rgba(54, 162, 235, 0.8)',
        'rgba(255, 206, 86, 0.8)',
        'rgba(75, 192, 192, 0.8)',
        'rgba(153, 102, 255, 0.8)',
        'rgba(255, 159, 64, 0.8)',
        'rgba(199, 199, 199, 0.8)',
        'rgba(83, 102, 255, 0.8)',
        'rgba(255, 99, 255, 0.8)'
    ];
    
    chartDistribucion = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colores,
                borderWidth: 2,
                borderColor: '#fff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        generateLabels: function(chart) {
                            const data = chart.data;
                            return data.labels.map((label, i) => {
                                const value = data.datasets[0].data[i];
                                return {
                                    text: `${label}: ${value}`,
                                    fillStyle: data.datasets[0].backgroundColor[i],
                                    hidden: false,
                                    index: i
                                };
                            });
                        }
                    }
                }
            }
        }
    });
}

/**
 * GRÁFICO DE ACTIVIDAD POR HORA
 */
function crearGraficoActividad() {
    const ctx = document.getElementById('chartActividad');
    if (!ctx) return;
    
    const { actividad_horas } = dashboardData;
    
    if (chartActividad) {
        chartActividad.destroy();
    }
    
    chartActividad = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: actividad_horas.map(h => h.hora),
            datasets: [{
                label: 'Movimientos',
                data: actividad_horas.map(h => h.movimientos),
                backgroundColor: CONFIG.CHART_COLORS.primary,
                borderColor: CONFIG.CHART_COLORS.primary,
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
}

/**
 * ACTUALIZAR TOP PRODUCTOS
 */
function actualizarTopProductos() {
    const tbody = document.querySelector('#tableTopProductos tbody');
    if (!tbody) return;
    
    const { top_productos } = dashboardData;
    
    if (!top_productos || top_productos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="no-data">No hay datos disponibles</td></tr>';
        return;
    }
    
    tbody.innerHTML = top_productos.map((producto, index) => {
        const totalKg = toNumber(producto.total_kg);
        return `
            <tr>
                <td><strong>${index + 1}</strong></td>
                <td>${producto.producto__nombre || 'Sin nombre'}</td>
                <td>${producto.total_movimientos || 0}</td>
                <td>${totalKg.toFixed(2)} kg</td>
            </tr>
        `;
    }).join('');
}

/**
 * ACTUALIZAR ALERTAS
 */
function actualizarAlertas() {
    const container = document.getElementById('alertasContainer');
    const badge = document.getElementById('alertCount');
    
    if (!container || !badge) return;
    
    const { productos_bajo_stock } = dashboardData;
    
    badge.textContent = productos_bajo_stock ? productos_bajo_stock.length : 0;
    
    if (!productos_bajo_stock || productos_bajo_stock.length === 0) {
        container.innerHTML = '<p class="no-data">Todo en orden 👍</p>';
        return;
    }
    
    container.innerHTML = productos_bajo_stock.map(p => {
        const esCritica = p.porcentaje_stock < 50;
        return `
            <div class="alerta-item ${esCritica ? 'critica' : ''}">
                <div class="alerta-content">
                    <div class="alerta-producto">${p.nombre}</div>
                    <div class="alerta-detalle">
                        Stock: ${p.stock_actual} / ${p.stock_minimo} 
                        (${p.porcentaje_stock}%)
                    </div>
                </div>
                <span class="alerta-badge-small">-${p.deficit}</span>
            </div>
        `;
    }).join('');
}

/**
 * ACTUALIZAR ÚLTIMOS MOVIMIENTOS
 */
function actualizarUltimosMovimientos() {
    const container = document.getElementById('ultimosMovimientos');
    if (!container) return;
    
    const { ultimos_movimientos } = dashboardData;
    
    if (!ultimos_movimientos || ultimos_movimientos.length === 0) {
        container.innerHTML = '<p class="no-data">No hay movimientos recientes</p>';
        return;
    }
    
    container.innerHTML = ultimos_movimientos.map(m => {
        const totalPeso = toNumber(m.total_peso);
        return `
            <div class="movement-item ${m.tipo}">
                <div class="movement-info">
                    <div class="movement-tipo">
                        ${m.tipo === 'ingreso' ? '📥 Ingreso' : '📤 Retiro'}
                        ${m.origen ? `desde ${m.origen}` : ''}
                        ${m.destino ? `hacia ${m.destino}` : ''}
                    </div>
                    <div class="movement-detalle">
                        Grupo #${m.grupo_id}
                    </div>
                    <div class="movement-fecha">${m.fecha}</div>
                </div>
                <div class="movement-stats">
                    <div class="movement-peso">${totalPeso.toFixed(2)} kg</div>
                    <div class="movement-items">${m.cantidad_items} items</div>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * ACTUALIZAR PRODUCTOS SIN MOVIMIENTO
 */
function actualizarProductosSinMovimiento() {
    const container = document.getElementById('productosSinMovimiento');
    if (!container) return;
    
    const { productos_sin_movimiento } = dashboardData;
    
    if (!productos_sin_movimiento || productos_sin_movimiento.length === 0) {
        container.innerHTML = '<p class="no-data">Todos los productos tienen movimiento 👍</p>';
        return;
    }
    
    container.innerHTML = productos_sin_movimiento.map(p => `
        <div class="product-badge">
            <div class="product-name">${p.nombre}</div>
            <div class="product-stock">Stock: ${p.stock_actual}</div>
        </div>
    `).join('');
}

/**
 * ACTUALIZAR ORÍGENES Y DESTINOS
 */
function actualizarOrigenesDestinos() {
    // Orígenes
    const containerOrigenes = document.getElementById('topOrigenes');
    if (containerOrigenes) {
        const { top_origenes } = dashboardData;
        
        if (!top_origenes || top_origenes.length === 0) {
            containerOrigenes.innerHTML = '<p class="no-data">No hay datos</p>';
        } else {
            containerOrigenes.innerHTML = top_origenes.map(o => {
                const kgTotal = toNumber(o.kg_total);
                return `
                    <div class="list-item">
                        <span class="list-item-name">${o.origen}</span>
                        <div class="list-item-stats">
                            <span>${o.cantidad} mov.</span>
                            <span>${kgTotal.toFixed(2)} kg</span>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }
    
    // Destinos
    const containerDestinos = document.getElementById('topDestinos');
    if (containerDestinos) {
        const { top_destinos } = dashboardData;
        
        if (!top_destinos || top_destinos.length === 0) {
            containerDestinos.innerHTML = '<p class="no-data">No hay datos</p>';
        } else {
            containerDestinos.innerHTML = top_destinos.map(d => {
                const kgNeto = toNumber(d.kg_neto ?? d.kg_total);
                const kgDevuelto = toNumber(d.kg_devuelto ?? 0);
                return `
                    <div class="list-item">
                        <span class="list-item-name">${d.boca_salida}</span>
                        <div class="list-item-stats">
                            <span>${d.cantidad} mov.</span>
                            <span>${kgNeto.toFixed(2)} kg neto</span>
                            ${kgDevuelto > 0 ? `<span style="color:#10b981;font-size:.8em;">↩ ${kgDevuelto.toFixed(2)} kg devuelto</span>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }
    }
}

/**
 * ACTUALIZAR RESUMEN DEL MES
 */
function actualizarResumen30Dias(resumen) {
    const contenedor = document.getElementById('resumen-30dias');
    if (!contenedor || !resumen) return;
    
    contenedor.style.display = 'block';
    contenedor.innerHTML = `
        <div class="resumen-mes-grid">
            <div class="resumen-item">
                <span class="resumen-label">📅 Días transcurridos:</span>
                <span class="resumen-value">${resumen.total_dias}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📥 Total Ingresos:</span>
                <span class="resumen-value text-success">${resumen.total_ingresos}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📤 Total Retiros:</span>
                <span class="resumen-value text-danger">${resumen.total_retiros}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📊 Promedio/día (Ingresos):</span>
                <span class="resumen-value">${resumen.promedio_ingresos_dia}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📊 Promedio/día (Retiros):</span>
                <span class="resumen-value">${resumen.promedio_retiros_dia}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Ingresados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_ingresados).toFixed(2)} kg</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Retirados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_retirados).toFixed(2)} kg</span>
            </div>
        </div>
    `;
}

/**
 * UTILIDADES
 */
function animarNumero(elementId, valorFinal) {
    const elemento = document.getElementById(elementId);
    if (!elemento) return;
    
    const valorInicial = parseFloat(elemento.textContent) || 0;
    const duracion = 1000;
    const incremento = (valorFinal - valorInicial) / (duracion / 16);
    
    let valorActual = valorInicial;
    
    const intervalo = setInterval(() => {
        valorActual += incremento;
        
        if ((incremento > 0 && valorActual >= valorFinal) || 
            (incremento < 0 && valorActual <= valorFinal)) {
            valorActual = valorFinal;
            clearInterval(intervalo);
        }
        
        if (elementId === 'totalKilos') {
            elemento.textContent = valorActual.toFixed(2);
        } else {
            elemento.textContent = Math.round(valorActual);
        }
    }, 16);
}

function mostrarLoading(mostrar) {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        if (mostrar) {
            overlay.classList.add('active');
        } else {
            overlay.classList.remove('active');
        }
    }
}

function mostrarError(mensaje) {
    console.error(mensaje);
    alert(mensaje);
}

/**
 * FUNCIONES PÚBLICAS
 */
function actualizarDashboard() {
    console.log('🔄 Actualizando dashboard...');
    cargarDatos();
}

/**
 * FUNCIONES PÚBLICAS
 */
function actualizarDashboard() {
    console.log('🔄 Actualizando dashboard...');
    cargarDashboard();
}

function toggleAutoRefresh() {
    isAutoRefresh = !isAutoRefresh;
    const btn = document.getElementById('autoRefreshBtn');
    
    if (!btn) return;
    
    if (isAutoRefresh) {
        btn.classList.add('active');
        btn.title = 'Desactivar auto-actualización';
        autoRefreshInterval = setInterval(cargarDashboard, CONFIG.REFRESH_INTERVAL);
        console.log('✅ Auto-refresh activado');
        if (window.Toast) {
            window.Toast.info('Auto-actualización activada');
        }
    } else {
        btn.classList.remove('active');
        btn.title = 'Activar auto-actualización';
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
        }
        console.log('❌ Auto-refresh desactivado');
        if (window.Toast) {
            window.Toast.info('Auto-actualización desactivada');
        }
    }
}

/**
 * INICIALIZACIÓN DEL DASHBOARD
 */
function inicializarDashboard() {
    console.log('🚀 Inicializando dashboard...');
    
    // Event listener para el selector de período
    const selector = document.getElementById('periodo-selector');
    if (selector) {
        selector.addEventListener('change', function() {
            const valor = this.value;
            console.log('📊 Período seleccionado:', valor);
            
            if (valor === 'custom') {
                // Mostrar campos de fecha
                mostrarFechasCustom();
            } else {
                // Ocultar campos y cargar período predefinido
                ocultarFechasCustom();
                cargarDashboard();
            }
        });
    }
    
    // Establecer fechas por defecto
    establecerFechasPorDefecto();

    // Marcar la card activa inicial
    sincronizarEstadoCats();

    // Carga inicial
    cargarDashboard();
}

function mostrarFechasCustom() {
    const customDates = document.getElementById('custom-dates');
    if (customDates) {
        customDates.style.display = 'block';
    }
}

function ocultarFechasCustom() {
    const customDates = document.getElementById('custom-dates');
    if (customDates) {
        customDates.style.display = 'none';
    }
}

function establecerFechasPorDefecto() {
    const fechaHasta = document.getElementById('fecha-hasta');
    const fechaDesde = document.getElementById('fecha-desde');
    
    if (fechaHasta && fechaDesde) {
        // Fecha actual
        const hoy = new Date();
        fechaHasta.value = hoy.toISOString().split('T')[0];
        
        // 30 días atrás
        const hace30 = new Date();
        hace30.setDate(hace30.getDate() - 30);
        fechaDesde.value = hace30.toISOString().split('T')[0];
    }
}

function aplicarPeriodoCustom() {
    const fechaDesde = document.getElementById('fecha-desde')?.value;
    const fechaHasta = document.getElementById('fecha-hasta')?.value;
    
    if (!fechaDesde || !fechaHasta) {
        alert('Por favor seleccioná ambas fechas');
        return;
    }
    
    // Validar que desde sea menor que hasta
    if (new Date(fechaDesde) > new Date(fechaHasta)) {
        alert('La fecha "Desde" debe ser anterior a la fecha "Hasta"');
        return;
    }
    
    console.log('📅 Aplicando período custom:', fechaDesde, 'a', fechaHasta);
    
    // Cargar datos con fechas personalizadas
    cargarDashboardCustom(fechaDesde, fechaHasta);
}

async function cargarDashboardCustom(desde, hasta) {
    mostrarLoading(true);
    
    try {
        // Construir URL con parámetros de fecha y categoría activa
        const catParam = currentCategoria ? `&categoria=${currentCategoria}` : '';
        const url = `${CONFIG.API_URL}?desde=${desde}&hasta=${hasta}${catParam}`;
        
        console.log('🌐 Cargando datos custom:', url);
        
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        dashboardData = await response.json();
        console.log('✅ Datos custom cargados:', dashboardData);
        
        // Actualizar solo el gráfico de movimientos
        actualizarGraficoMovimientos();
        
        // Actualizar resumen si existe
        const selector = document.getElementById('periodo-selector');
        const resumen30 = document.getElementById('resumen-30dias');
        
        if (resumen30 && dashboardData.resumen_custom) {
            resumen30.style.display = 'block';
            actualizarResumenCustom(dashboardData.resumen_custom, desde, hasta);
        }
        
    } catch (error) {
        console.error('❌ Error cargando datos custom:', error);
        alert('Error al cargar los datos del período seleccionado');
    } finally {
        mostrarLoading(false);
    }
}

function actualizarResumenCustom(resumen, desde, hasta) {
    const contenedor = document.getElementById('resumen-30dias');
    if (!contenedor || !resumen) return;
    
    // Calcular días
    const fechaDesde = new Date(desde);
    const fechaHasta = new Date(hasta);
    const diffTime = Math.abs(fechaHasta - fechaDesde);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
    
    contenedor.style.display = 'block';
    contenedor.innerHTML = `
        <div class="resumen-mes-grid">
            <div class="resumen-item">
                <span class="resumen-label">📅 Período:</span>
                <span class="resumen-value">${diffDays} días</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📆 Desde:</span>
                <span class="resumen-value">${formatearFecha(desde)}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📆 Hasta:</span>
                <span class="resumen-value">${formatearFecha(hasta)}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📥 Total Ingresos:</span>
                <span class="resumen-value text-success">${resumen.total_ingresos || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📤 Total Retiros:</span>
                <span class="resumen-value text-danger">${resumen.total_retiros || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Ingresados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_ingresados).toFixed(2)} kg</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Retirados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_retirados).toFixed(2)} kg</span>
            </div>
        </div>
    `;
}

function formatearFecha(fechaStr) {
    const fecha = new Date(fechaStr);
    return fecha.toLocaleDateString('es-AR', { 
        day: '2-digit', 
        month: '2-digit', 
        year: 'numeric' 
    });
}


/**
 * ACTUALIZAR GRÁFICO DE MOVIMIENTOS
 * Soporta: 7 días, 30 días, y período personalizado
 */
function actualizarGraficoMovimientos() {
    const ctx = document.getElementById('chartMovimientos');
    if (!ctx) {
        console.warn('⚠️ Canvas chartMovimientos no encontrado');
        return;
    }
    
    // Obtener período seleccionado
    const periodoSelector = document.getElementById('periodo-selector');
    const periodo = periodoSelector ? periodoSelector.value : '7dias';
    
    console.log('📊 Actualizando gráfico con período:', periodo);
    
    let labels, dataIngresos, dataRetiros, tooltipData, titulo;
    
    // Determinar qué datos usar según el período
    if (periodo === 'custom' && dashboardData.movimientos_custom) {
        // Datos personalizados
        labels = dashboardData.movimientos_custom.map(m => m.fecha);
        dataIngresos = dashboardData.movimientos_custom.map(m => m.ingresos);
        dataRetiros = dashboardData.movimientos_custom.map(m => m.retiros);
        tooltipData = dashboardData.movimientos_custom;
        titulo = 'Movimientos - Período Personalizado';
        
        console.log('   Usando datos custom:', dashboardData.movimientos_custom.length, 'días');
        
    } else if (periodo === '30dias' && dashboardData.movimientos_30_dias) {
        // Últimos 30 días
        labels = dashboardData.movimientos_30_dias.map(m => m.fecha);
        dataIngresos = dashboardData.movimientos_30_dias.map(m => m.ingresos);
        dataRetiros = dashboardData.movimientos_30_dias.map(m => m.retiros);
        tooltipData = dashboardData.movimientos_30_dias;
        titulo = 'Movimientos de los Últimos 30 Días';
        
        console.log('   Usando datos 30 días');
        
    } else {
        // Últimos 7 días (por defecto)
        labels = dashboardData.movimientos_7_dias.map(m => m.fecha);
        dataIngresos = dashboardData.movimientos_7_dias.map(m => m.ingresos);
        dataRetiros = dashboardData.movimientos_7_dias.map(m => m.retiros);
        tooltipData = dashboardData.movimientos_7_dias;
        titulo = 'Movimientos Últimos 7 Días';
        
        console.log('   Usando datos 7 días');
    }
    
    // Destruir gráfico anterior si existe
    if (chartMovimientos) {
        chartMovimientos.destroy();
    }
    
    // Crear nuevo gráfico
    chartMovimientos = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Ingresos',
                    data: dataIngresos,
                    borderColor: CONFIG.CHART_COLORS.ingreso,
                    backgroundColor: CONFIG.CHART_COLORS.ingresoLight,
                    tension: 0.4,
                    fill: true,
                    borderWidth: 2
                },
                {
                    label: 'Retiros',
                    data: dataRetiros,
                    borderColor: CONFIG.CHART_COLORS.retiro,
                    backgroundColor: CONFIG.CHART_COLORS.retiroLight,
                    tension: 0.4,
                    fill: true,
                    borderWidth: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                title: {
                    display: true,
                    text: titulo
                },
                tooltip: {
                    callbacks: {
                        afterLabel: function(context) {
                            const index = context.dataIndex;
                            const kg = context.dataset.label === 'Ingresos' 
                                ? tooltipData[index].kg_ingresados
                                : tooltipData[index].kg_retirados;
                            return `${toNumber(kg).toFixed(2)} kg`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1,
                        precision: 0
                    }
                }
            }
        }
    });
    
    console.log('✅ Gráfico actualizado exitosamente');
    
    // Actualizar resumen según el período
    actualizarResumenSegunPeriodo(periodo);
}

/**
 * ACTUALIZAR RESUMEN SEGÚN EL PERÍODO
 */
function actualizarResumenSegunPeriodo(periodo) {
    const resumenDiv = document.getElementById('resumen-30dias');
    if (!resumenDiv) return;
    
    if (periodo === 'custom' && dashboardData.resumen_custom) {
        // Mostrar resumen custom
        resumenDiv.style.display = 'block';
        
        const fechaDesde = document.getElementById('fecha-desde')?.value;
        const fechaHasta = document.getElementById('fecha-hasta')?.value;
        
        actualizarResumenCustom(dashboardData.resumen_custom, fechaDesde, fechaHasta);
        
    } else if (periodo === '30dias' && dashboardData.resumen_30_dias) {
        // Mostrar resumen 30 días
        resumenDiv.style.display = 'block';
        actualizarResumen30Dias(dashboardData.resumen_30_dias);
        
    } else {
        // Ocultar resumen para 7 días
        resumenDiv.style.display = 'none';
    }
}

/**
 * ACTUALIZAR RESUMEN DE 30 DÍAS
 */
function actualizarResumen30Dias(resumen) {
    const contenedor = document.getElementById('resumen-30dias');
    if (!contenedor || !resumen) return;
    
    contenedor.style.display = 'block';
    contenedor.innerHTML = `
        <div class="resumen-mes-grid">
            <div class="resumen-item">
                <span class="resumen-label">📅 Período:</span>
                <span class="resumen-value">30 días</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📥 Total Ingresos:</span>
                <span class="resumen-value text-success">${resumen.total_ingresos || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📤 Total Retiros:</span>
                <span class="resumen-value text-danger">${resumen.total_retiros || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📊 Promedio/día (Ingresos):</span>
                <span class="resumen-value">${resumen.promedio_ingresos_dia || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📊 Promedio/día (Retiros):</span>
                <span class="resumen-value">${resumen.promedio_retiros_dia || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Ingresados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_ingresados).toFixed(2)} kg</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Retirados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_retirados).toFixed(2)} kg</span>
            </div>
        </div>
    `;
}

/**
 * ACTUALIZAR RESUMEN PERSONALIZADO
 */
function actualizarResumenCustom(resumen, desde, hasta) {
    const contenedor = document.getElementById('resumen-30dias');
    if (!contenedor || !resumen) return;
    
    // Calcular días del período
    const fechaDesde = new Date(desde + 'T00:00:00');
    const fechaHasta = new Date(hasta + 'T00:00:00');
    const diffTime = Math.abs(fechaHasta - fechaDesde);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
    
    // Calcular promedios
    const promedioIngresos = diffDays > 0 ? (resumen.total_ingresos / diffDays).toFixed(1) : 0;
    const promedioRetiros = diffDays > 0 ? (resumen.total_retiros / diffDays).toFixed(1) : 0;
    
    contenedor.style.display = 'block';
    contenedor.innerHTML = `
        <div class="resumen-mes-grid">
            <div class="resumen-item">
                <span class="resumen-label">📅 Período:</span>
                <span class="resumen-value">${diffDays} día${diffDays !== 1 ? 's' : ''}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📆 Desde:</span>
                <span class="resumen-value">${formatearFecha(desde)}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📆 Hasta:</span>
                <span class="resumen-value">${formatearFecha(hasta)}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📥 Total Ingresos:</span>
                <span class="resumen-value text-success">${resumen.total_ingresos || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📤 Total Retiros:</span>
                <span class="resumen-value text-danger">${resumen.total_retiros || 0}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📊 Promedio/día (Ingresos):</span>
                <span class="resumen-value">${promedioIngresos}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">📊 Promedio/día (Retiros):</span>
                <span class="resumen-value">${promedioRetiros}</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Ingresados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_ingresados).toFixed(2)} kg</span>
            </div>
            <div class="resumen-item">
                <span class="resumen-label">⚖️ Total kg Retirados:</span>
                <span class="resumen-value">${toNumber(resumen.total_kg_retirados).toFixed(2)} kg</span>
            </div>
        </div>
    `;
}

/**
 * FORMATEAR FECHA (DD/MM/YYYY)
 */
function formatearFecha(fechaStr) {
    if (!fechaStr) return '';
    const fecha = new Date(fechaStr + 'T00:00:00');
    return fecha.toLocaleDateString('es-AR', { 
        day: '2-digit', 
        month: '2-digit', 
        year: 'numeric' 
    });
}

/**
 * HELPER: Convertir a número seguro
 */
function toNumber(value, defaultValue = 0) {
    const num = parseFloat(value);
    return isNaN(num) ? defaultValue : num;
}
// Exportar funciones globales
window.inicializarDashboard = inicializarDashboard;
window.actualizarDashboard = actualizarDashboard;
window.cargarDashboard = cargarDashboard;
window.toggleAutoRefresh = toggleAutoRefresh;
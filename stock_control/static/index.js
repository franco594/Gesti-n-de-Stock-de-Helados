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
  if (!modalAbierta) return;
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
    btn.textContent = "✕";
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

async function actualizarTotales() {
  try {
    const data = await getJSON(API.obtenerStock);
    if (Array.isArray(data?.stock)) {
      const totalBaldes = data.stock.reduce((acc, it) => acc + Number(it.cantidad || 0), 0);
      const elBaldes = document.getElementById('totalBaldes');
      if (elBaldes) elBaldes.textContent = String(totalBaldes);
    }
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
  actualizarTotales();
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
      tr.innerHTML = `
        <td>${p.plu}</td>
        <td>${p.nombre}</td>
        <td>${p.stock_minimo}</td>
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
});

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
  cerrarModalAdminProductos,
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
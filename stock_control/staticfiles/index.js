let productosEscaneados = [];
let modo = '';
let modalAbierta = false; // Controla si el escaneo está habilitado
let faltantesSet = new Set();
let bocaSeleccionada = '';



if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js")
        .then((reg) => console.log("✅ Service Worker registrado:", reg))
        .catch((err) => console.error("❌ Error registrando Service Worker:", err));
}

let deferredPrompt;

window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    document.getElementById("installBtn").style.display = "block";
});

document.getElementById("installBtn").addEventListener("click", () => {
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then((choiceResult) => {
        if (choiceResult.outcome === "accepted") {
            console.log("✅ El usuario instaló la app");
        }
        deferredPrompt = null;
    });
});



console.log("📢 DOM completamente cargado.");

// Obtener elementos del DOM
const stockModal = document.getElementById("stockModal");
const stockTable = document.getElementById("stockTable");
const configButton = document.getElementById("configButton");
const closeModal = document.querySelector(".close");
const codigoScanner = document.getElementById("codigoScanner");
const contenedorIngresar = document.getElementById("contenedor-input-ingresar");
const contenedorRetirar = document.getElementById("contenedor-input-retirar");
const tablaGeneral = document.getElementById("stockTable");
const vistaGrupos = document.getElementById("vistaGrupos");

codigoScanner.disabled = true;

// ✅ Función para activar el input de escaneo cuando la modal está abierta
function activarInputEscaneo() {
    codigoScanner.disabled = false;
    codigoScanner.focus();
}

// ❌ Función para desactivar el input de escaneo cuando la modal se cierra
function desactivarInputEscaneo() {
    codigoScanner.disabled = true;
    codigoScanner.blur();
}

// ✅ Escanear solo si la modal está abierta y actualizar en tiempo real
codigoScanner.addEventListener("keydown", function(event) {
    console.log("🔍 Evento detectado. Modal abierta:", modalAbierta, "| Tecla presionada:", event.key);

    if (!modalAbierta) {
        console.warn("⛔ Escaneo bloqueado porque la modal está cerrada.");
        return; // No procesar si la modal está cerrada
    }

    if (event.key === "Enter") {
        event.preventDefault();
        const codigo = codigoScanner.value.trim();

        if (codigo.length === 13 && !isNaN(codigo)) {
            console.log("📡 Código escaneado:", codigo);
            procesarCodigoEscaneado(codigo);
            codigoScanner.value = ""; // Limpiar el input después de procesarlo
        } else {
            console.warn("⚠️ Código inválido:", codigo);
        }
    }
});

function abrirModal(tipo) {
    modo = tipo;
    modalAbierta = true;
    console.log(`📢 Modal abierta: ${tipo}`);
    codigoScanner.style.visibility = "visible";

    // Agregar input de escaneo al contenedor correcto
    const contenedorIngresar = document.getElementById("contenedor-input-ingresar");
    const contenedorRetirar = document.getElementById("contenedor-input-retirar");

    if (tipo === "ingresar") {
        contenedorIngresar.appendChild(codigoScanner);
    } else {
        contenedorRetirar.appendChild(codigoScanner);
    }

    // Mostrar el campo de boca de salida u origen según el tipo
    const inputContainer = document.getElementById(`contenedor-boca-${tipo}`);
    const endpoint = tipo === 'retirar' ? "/api/obtener_bocas_salida/" : "/api/obtener_origenes/";

    console.log(endpoint);

    fetch(endpoint)
    .then(response => response.json())
    .then(data => {
        if (data.lista && data.lista.length > 0) {
            // 🔁 Reordenar: Portofino primero, el resto después
            const lista = data.lista.map(nombre => nombre.trim());
            const preferida = "Portofino";
            const listaOrdenada = [
                ...lista.filter(n => n === preferida),
                ...lista.filter(n => n !== preferida)
            ];

            const primeraSeleccion = listaOrdenada[0];

            inputContainer.innerHTML = `
                <label>${tipo === 'retirar' ? 'Boca de salida' : 'Ingresar a'}:</label>
                <div id="bocas-container-${tipo}" class="bocas-container">
                    ${listaOrdenada.map((nombre, i) => {
                        const clase = i === 0 ? "boca-btn seleccionada" : "boca-btn";
                        return `<button class="${clase}" data-nombre="${nombre}" onclick="seleccionarBoca('${nombre}', '${tipo}')">📍 ${nombre}</button>`;
                    }).join('')}
                </div>
                <input type="hidden" id="input-boca-${tipo}" value="${primeraSeleccion}">
            `;
        }
    });

    fetch("/api/reiniciar_lista_temporal/", { method: "POST" })
        .then(() => {
            productosEscaneados = [];
            actualizarListaEscaneados(modo, []);
        })
        .catch(error => console.error("Error al reiniciar la lista:", error));

    const modal = document.getElementById(`modal-${tipo}`);
    if (!modal) {
        console.error(`⚠️ No se encontró la modal: modal-${tipo}`);
        return;
    }

    modal.style.display = "block";
    modal.classList.remove("fade-out");

    activarInputEscaneo();
    obtenerProductosEscaneados();

    setTimeout(() => {
        codigoScanner.focus();
    }, 100);
}


let tipoActualCrear = "";

function abrirModalCrearBoca(tipo) {
    tipoActualCrear = tipo;

    document.getElementById("nombreNuevaBoca").value = "";
    document.getElementById("errorCrearBoca").style.display = "none";

    document.getElementById("tituloCrearBoca").textContent =
        tipo === 'retirar' ? "Crear nueva boca de salida" : "Crear nuevo origen";

    // Mostrar la modal
    document.getElementById("modalCrearBoca").style.display = "block";

    // Obtener chips existentes
    const endpoint = tipo === 'retirar' ? "/api/obtener_bocas_salida/" : "/api/obtener_origenes/";

    fetch(endpoint)
        .then(response => response.json())
        .then(data => {
            const container = document.getElementById("chipsExistentes");
            container.innerHTML = "";

            if (data.lista && data.lista.length > 0) {
                data.lista.forEach(nombre => {
                    const chip = document.createElement("div");
                    chip.className = "chip";
                    chip.innerHTML = `📍 ${nombre.trim()} <span class="close-chip" onclick="eliminarBocaDesdeModal('${nombre.trim()}')">&times;</span>`;
                    container.appendChild(chip);
                });
            } else {
                container.innerHTML = "<p style='font-style: italic;'>No hay opciones creadas.</p>";
            }
        });
}

function cerrarModalCrearBoca() {
    document.getElementById("modalCrearBoca").style.display = "none";
}

function confirmarCreacionBoca() {
    const nombre = document.getElementById("nombreNuevaBoca").value.trim();
    if (!nombre) {
        document.getElementById("errorCrearBoca").textContent = "El nombre no puede estar vacío.";
        document.getElementById("errorCrearBoca").style.display = "block";
        return;
    }

    const endpoint = tipoActualCrear === 'retirar' ? "/api/crear_boca_salida/" : "/api/crear_origen/";

    fetch(endpoint, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ nombre })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            abrirModalCrearBoca(tipoActualCrear);  // Recargar chips
        } else {
            document.getElementById("errorCrearBoca").textContent = data.error || "Error al crear.";
            document.getElementById("errorCrearBoca").style.display = "block";
        }
    });
}

function eliminarBocaDesdeModal(nombre) {
    if (!confirm(`¿Eliminar "${nombre}"?`)) return;

    const endpoint = tipoActualCrear === 'retirar' ? "/api/eliminar_boca_salida/" : "/api/eliminar_origen/";

    fetch(endpoint, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ nombre })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            abrirModalCrearBoca(tipoActualCrear);  // Recargar después de eliminar
        } else {
            alert("❌ Error al eliminar: " + (data.error || "Desconocido"));
        }
    });
}


function seleccionarBoca(nombre, tipo) {
    // Quitar la clase seleccionada de todos los botones
    document.querySelectorAll(`#bocas-container-${tipo} .boca-btn`).forEach(btn => {
        btn.classList.remove("seleccionada");
    });

    // Agregar la clase seleccionada al botón actual
    const botonSeleccionado = document.querySelector(`#bocas-container-${tipo} .boca-btn[data-nombre="${CSS.escape(nombre)}"]`);
    if (botonSeleccionado) {
        botonSeleccionado.classList.add("seleccionada");
    }

    // Actualizar el valor del input oculto
    document.getElementById(`input-boca-${tipo}`).value = nombre;
}




// ❌ Modificar la función cerrarModal para deshabilitar el input
function cerrarModal(tipo) {
    modalAbierta = false;
    console.log(`❌ Modal cerrada: ${tipo}`);

    const modal = document.getElementById(`modal-${tipo}`);
    const modalContent = document.getElementById(`modal-content-${tipo}`);
    if (!modal) {
        console.error(`⚠️ No se encontró la modal: modal-${tipo}`);
        return;
    }

    // Agregar clase fade-out para iniciar la animación
    modalContent.classList.add("zoom-out");
    modal.classList.add("fade-out");

    // Esperar el tiempo de la animación antes de ocultar la modal
    setTimeout(() => {
        modal.style.display = "none"; // Oculta la modal después de la animación
        modal.classList.remove("fade-out"); // Elimina la clase para la próxima vez que se abra
        modalContent.classList.remove("zoom-out");
        desactivarInputEscaneo(); // Deshabilitar el input de escaneo
    }, 300); // Debe coincidir con la duración de fadeOut en CSS
}

function cerrarModalDenegado() {
    document.getElementById(`modal-denegado`).classList.add("zoom-out"); // Oculta el modal
    document.getElementById(`modal-denegado`).classList.add("fade-out"); // Oculta el modal

    // Esperar el tiempo de la animación antes de ocultar la modal
    setTimeout(() => {
        document.getElementById(`modal-denegado`).style.display = "none"; // Oculta el modal 
        document.getElementById(`modal-denegado`).classList.remove("fade-out"); // Elimina la clase para la próxima vez que se abra
        document.getElementById(`modal-denegado`).classList.remove("zoom-out"); 
    }, 300); // Debe coincidir con la duración de fadeOut en CSS
}

function cerrarModalConfirmacion() {
    document.getElementById(`modal-confirmacion`).classList.add("zoom-out"); // Oculta el modal
    document.getElementById(`modal-confirmacion`).classList.add("fade-out"); // Oculta el modal

    // Esperar el tiempo de la animación antes de ocultar la modal
    setTimeout(() => {
        document.getElementById(`modal-confirmacion`).style.display = "none"; // Oculta el modal 
        document.getElementById(`modal-confirmacion`).classList.remove("fade-out"); // Elimina la clase para la próxima vez que se abra
        document.getElementById(`modal-confirmacion`).classList.remove("zoom-out"); 
    }, 300); // Debe coincidir con la duración de fadeOut en CSS
}

// ✅ Obtener productos escaneados y actualizar modal en tiempo real
function obtenerProductosEscaneados() {
    if (!modalAbierta) return; // 🔴 No solicitar datos si la modal está cerrada

    fetch('/api/obtener_productos_temporales/')
        .then(response => response.json())
        .then(data => {
            productosEscaneados = data.productos || [];
            actualizarListaEscaneados(modo, productosEscaneados);
        })
        .catch(error => console.error("Error al obtener productos escaneados:", error));
}

// ✅ Actualizar la lista en la modal en tiempo real
function actualizarListaEscaneados(modalTipo, productosEscaneados) {
    if (!modalAbierta) return; // 🔴 No actualizar si la modal está cerrada
    
    console.log("📌 Actualizando modal:", modalTipo, productosEscaneados);
    
    const lista = modalTipo === "retirar" 
        ? document.getElementById("listaEscaneadosRetiro")
        : document.getElementById("listaEscaneadosIngreso");

    if (!lista) {
        console.error("⚠️ No se encontró la lista del modal:", modalTipo);
        return;
    }

    lista.innerHTML = "";
    
    if (productosEscaneados.length === 0) {
        lista.innerHTML = "<p style='text-align:center; font-style:italic;'>No hay productos escaneados.</p>";
        return;
    }
    
    productosEscaneados.forEach((producto) => {
        const item = document.createElement("li");
        item.textContent = `Balde: ${producto.nombre}, Peso: ${producto.peso}g`;
        
        const botonEliminar = document.createElement("button");
        botonEliminar.classList.add("btnEliminar");
        botonEliminar.textContent = "❌";
        botonEliminar.style.cursor = "pointer";
        botonEliminar.onclick = () => eliminarProductoEscaneado(producto.plu, modalTipo);

        item.appendChild(botonEliminar);
        lista.appendChild(item);
    });

    // 🔴 Validar stock después de actualizar la lista de productos escaneados (solo en retiro)
    if (modalTipo === "retirar") {
        validarStockParaRetiro();
    }
}


function eliminarProductoEscaneado(plu, modalTipo) {
    fetch('/api/eliminar_producto_temporal/', {
        method: 'POST',
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plu }) // 🔥 Enviar solo el PLU del producto a eliminar
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log("🗑 Producto eliminado de la sesión:", plu);
            obtenerProductosEscaneados(); // ✅ Volver a cargar la lista desde la sesión
        } else {
            console.error("❌ Error al eliminar producto:", data.error);
        }
    })
    .catch(error => console.error("⚠️ Error en la petición:", error));
}


function actualizarTablas() {
    console.log("🔄 Actualizando tablas...");

    fetch('/api/obtener_stock/')
        .then(response => response.json())
        .then(data => {
            const tablaStock = document.getElementById("stockTable");

            if (!tablaStock) {
                console.error("⚠️ No se encontró la tabla de stock.");
                return;
            }

            // Verificar si la respuesta del backend es válida
            if (!data.stock || !Array.isArray(data.stock)) {
                console.error("❌ Error: La respuesta del backend no contiene una lista de stock.");
                return;
            }

            // Guardar el encabezado actual para que no se pierda
            const encabezado = `
                <thead>
                    <tr>
                        <th>Producto</th>
                        <th>Cantidad de Baldes</th>
                    </tr>
                </thead>
            `;

            let contenido = "<tbody>";

            if (data.stock.length === 0) {
                contenido += `
                    <tr>
                        <td colspan="2" style="text-align: center; font-style: italic; color: gray;">
                            No hay productos en stock.
                        </td>
                    </tr>
                `;
            } else {
                data.stock.forEach(item => {
                    // Aplicar la misma lógica de Jinja para resaltar stock bajo
                    let rowClass = item.cantidad < item.stock_minimo ? "resaltar-bajo-stock" : "";

                    contenido += `
                        <tr class="${rowClass}">
                            <td>${item.nombre}</td>
                            <td>${item.cantidad}</td>
                        </tr>
                    `;
                });
            }

            contenido += "</tbody>";

            // Mantener el encabezado y actualizar solo el cuerpo de la tabla
            tablaStock.innerHTML = encabezado + contenido;

            console.log("✅ Tabla de stock actualizada.");
        })
        .catch(error => console.error("❌ Error al actualizar la tabla de stock:", error));

        
}


function actualizarTablasGrupos() {
    fetch("/api/obtener_stock/")
        .then(response => response.json())
        .then(data => {
            if (!data || !Array.isArray(data.stock)) {
                console.error("❌ Error: La respuesta del backend no contiene una lista de stock válida.");
                return;
            }

            const gruposBody = {
                clasicos: document.getElementById("clasicos-body"),
                chocolates: document.getElementById("chocolates-body"),
                dulces: document.getElementById("dulces-body"),
                cremas: document.getElementById("cremas-body"),
                frutas: document.getElementById("frutas-body"),
                otros: document.getElementById("otros-body"),
            };

            // Verificar que cada contenedor exista antes de limpiar
            Object.keys(gruposBody).forEach(key => {
                if (gruposBody[key]) {
                    gruposBody[key].innerHTML = "";
                }
            });

            data.stock.forEach(producto => {
                let grupoAsignado = "otros";

                // Determinar el grupo del producto
                Object.entries(grupos).forEach(([grupo, productos]) => {
                    if (productos.includes(producto.nombre.toUpperCase())) {
                        grupoAsignado = grupo;
                    }
                });

                // Crear la fila de la tabla del grupo
                const fila = document.createElement("tr");
                fila.className = producto.cantidad < producto.stock_minimo ? "resaltar-bajo-stock" : "";
                fila.innerHTML = `<td>${producto.nombre}</td><td>${producto.cantidad}</td>`;

                // Agregar la fila a la tabla correspondiente
                if (gruposBody[grupoAsignado]) {
                    gruposBody[grupoAsignado].appendChild(fila);
                }
            });

            console.log("✅ Tablas de grupos actualizadas.");
        })
        .catch(error => console.error("❌ Error al obtener y actualizar los grupos:", error));
}



// Enviar el código al servidor Django para su procesamiento
function procesarCodigoEscaneado(codigo) {
    fetch("/api/procesar_codigo/", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ codigo: codigo })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            console.error("❌ Error procesando código:", data.error);
        } else {
            console.log("✔ Código procesado con éxito:", data);
            actualizarProductosEscaneados();  // Refrescar la lista de productos escaneados
            validarStockParaRetiro();
        }
    })
    .catch(error => console.error("⚠️ Error en la petición:", error));
}

function actualizarProductosEscaneados() {
    fetch('api/obtener_codigos')
        .then(response => response.json())
        .then(data => {

            // Verifica si 'productos' existe y es un array
            if (!data.productos || !Array.isArray(data.productos)) {
                console.error("❌ Error: La respuesta de la API no contiene un array válido.");
                return;
            }
            productosEscaneados = data || []; // Actualizar la lista con los productos escaneados
        })
        .catch(error => console.error("Error al obtener productos escaneados:", error));
}

// ✅ Capturar eventos de input para el escaneo cuando el modal está abierto
codigoScanner.addEventListener("keydown", function(event) {
    console.log("🔍 Evento detectado. Modal abierta:", modalAbierta, "| Tecla presionada:", event.key);

    if (!modalAbierta) {
        console.warn("⛔ Escaneo bloqueado porque la modal está cerrada.");
        return; // No procesar si la modal está cerrada
    }

    if (event.key === "Enter") {
        event.preventDefault();
        const codigo = codigoScanner.value.trim();

        if (codigo.length === 13 && !isNaN(codigo)) {
            console.log("📡 Código escaneado:", codigo);
            procesarCodigoEscaneado(codigo);
            codigoScanner.value = ""; // Limpiar el input después de procesarlo
        } else {
            console.warn("⚠️ Código inválido:", codigo);
        }
    }
});


// 🚀 Verificar cada 500ms si la modal está abierta antes de permitir escaneo y obtener datos actualizados
setInterval(() => {
    if (modalAbierta) {
        obtenerProductosEscaneados();
    }
}, 500);

// ✅ Mostrar modal de confirmación
function mostrarModalConfirmacion(mensaje) {
    const modal = document.getElementById("modal-confirmacion");
    const mensajeElemento = document.getElementById("mensajeConfirmacion");
    mensajeElemento.innerText = mensaje;
    modal.style.display = "block";
    
}

function mostrarModalDenegado(mensaje) {
    const modal = document.getElementById("modal-denegado");
    const mensajeElemento = document.getElementById("mensajeDenegado");
    mensajeElemento.innerText = mensaje;
    modal.style.display = "block";
    
}

// ✅ Confirmar y agregar los productos escaneados al servidor
function confirmarAgregarProductos() {
    console.log("📢 Intentando confirmar productos. Lista actual:", productosEscaneados);

    if (!productosEscaneados || productosEscaneados.length === 0) {
        mostrarModalDenegado("No hay productos escaneados para agregar.");
        console.warn("⛔ No hay productos escaneados para agregar.");
        return;
    }

    const boca = document.getElementById("input-boca-ingresar")?.value?.trim();

    if (!boca) {
        mostrarModalDenegado("Por favor, seleccioná un origen.");
        return;
    }

    const payload = { 
        productos: productosEscaneados,
        origen: boca
    };

    console.log("📤 Enviando datos al backend:", JSON.stringify(payload));

    fetch('/api/confirmar_codigos/', {
        method: 'POST',
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json().catch(() => response.text()))
    .then(data => {
        console.log("🔄 Respuesta del servidor:", data);

        if (data.error) {
            console.error("❌ Error al confirmar productos:", data.error);
        } else {  
            console.log("✅ Productos agregados correctamente.");
            mostrarModalConfirmacion(data.message);
            cerrarModal("ingresar");
            productosEscaneados = [];
            actualizarTablas();
            actualizarTablasGrupos();
        }
    })
    .catch(error => console.error("⚠️ Error al agregar productos:", error));
}




// ✅ Confirmar y retirar productos escaneados
async function confirmarRetirarProductos() {
    const hayStockSuficiente = await validarStockParaRetiro();
    const faltantes = Array.from(faltantesSet).join("\n");

    if (!hayStockSuficiente) {
        mostrarModalDenegado(`No se puede continuar con el retiro porque hay productos sin stock:\n${faltantes}`);
        return;
    }

    if (productosEscaneados.length === 0) {
        mostrarModalDenegado("No hay productos escaneados para retirar.");
        return;
    }

    const boca = document.getElementById("input-boca-retirar")?.value?.trim();


    if (!boca) {
        mostrarModalDenegado("Por favor, seleccioná una boca de salida.");
        return;
    }

    const payload = {
        productos: productosEscaneados,
        destino: boca  // ✅ esta clave es la que espera la vista en Django
    };

    fetch('/api/confirmar_retiro/', {
        method: 'POST',
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            console.error("❌ Error al retirar productos:", data.error);
            return;
        }

        console.log("✅ Productos retirados correctamente.");
        mostrarModalConfirmacion(data.message);
        cerrarModal("retirar");
        productosEscaneados = [];
        actualizarTablas();
        actualizarTablasGrupos();
    })
    .catch(error => console.error("❌ Error al retirar productos:", error));
}



async function validarStockParaRetiro() {
    try {
        const responseStock = await fetch('/api/stock_detallado/');
        const dataStock = await responseStock.json();

        const responseEscaneados = await fetch('/api/obtener_productos_temporales/');
        const dataEscaneados = await responseEscaneados.json();

        if (!dataStock || !dataStock.stock_detallado || !dataEscaneados || !dataEscaneados.productos) {
            console.error("Error al obtener los datos de stock o productos escaneados.");
            return false;
        }

        const stockProductos = dataStock.stock_detallado;
        const productosEscaneados = dataEscaneados.productos;
        let hayStockInsuficiente = false;

        productosEscaneados.forEach(producto => {
            const productoStock = stockProductos.find(p => p.nombre === producto.nombre);
            if (productoStock) {
                const cantidadDisponible = productoStock.cantidad;
                const cantidadRetirar = productosEscaneados.filter(p => p.nombre === producto.nombre).length;

                if (cantidadDisponible < cantidadRetirar) {
                    faltantesSet.add(`${producto.nombre} ❗`); // ✅ Agrega al Set (evita duplicados)
                    hayStockInsuficiente = true;

                    const filaProducto = document.querySelector(`.producto-fila[data-nombre="${producto.nombre}"]`);
                    if (filaProducto) {
                        filaProducto.classList.add("sin-stock");
                    }
                }
            }
            
        });

        const botonRetiro = document.getElementById("boton-retirar");
        const mensajeError = document.getElementById("mensaje-error");

        if (hayStockInsuficiente) {
            if (mensajeError) {
                mensajeError.innerText = "⚠️ Algunos productos no tienen stock suficiente.";
                mensajeError.style.display = "block";
            }
            if (botonRetiro) {
                botonRetiro.disabled = true;
            }
            return false; // 🔴 Indica que hay productos sin stock
        } else {
            if (mensajeError) mensajeError.style.display = "none";
            if (botonRetiro) botonRetiro.disabled = false;
            return true; // ✅ Indica que se puede proceder
        }

    } catch (error) {
        console.error("Error al validar el stock para retiro:", error);
        return false;
    }
}


/* Transición suave de Salida */ 

document.addEventListener("DOMContentLoaded", function () {
    // Transición de entrada cuando la página se carga
    document.body.classList.add("page-transition");

    // Transición de salida antes de cambiar de página
    document.querySelectorAll("a").forEach(link => {
        link.addEventListener("click", function (event) {
            const href = this.getAttribute("href");

            // Evita la transición si es un enlace externo o #
            if (!href || href.startsWith("#") || href.includes("javascript")) return;

            event.preventDefault(); // Detiene la navegación

            // Agrega la animación de salida
            document.body.style.opacity = "0";

            // Espera el tiempo de la animación antes de cambiar la página
            setTimeout(() => {
                window.location.href = href;
            }, 300);
        });
    });
});

document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("botonVistaGrupos").addEventListener("click", mostrarVistaGrupos);
});

const grupos = {
    clasicos: ["AMERICANA", "CHOCOLATE", "VAINILLA", "LIMON", "DCE LECHE", "FRUTILLA AL AGUA"],
    chocolates: ["CHOCOLAE BLOCK", "CH. CABSHA", "AMARGO", "CH. ALMENDRAS", "CH. PASAS RHUM", "CHOCOLAT PORTOFINO", "CHOCOLATE INTENSO", "CHOCOLAT DEBILIDAD", "CHOC. BLANCO", "ROCHER", "TOFFEE BLANCO"],
    dulces: ["DCE. LECHE NUEZ", "DCE. GRANIZADO", "SUPER DCE LECHE", "DCE. VAUQUITA", "D. LECHE PORTOFINO", "DCE. LECHE COOKIES", "BASE DULCE LECHE", "CHOCOTORTA"],
    cremas: ["TRAMONTANA", "ALMENDRADO", "CREMA RUSA", "GRANIZADO", "MENTA GRANIZADA", "CREMA FLAN", "FRUTOS DEL BOSQUE", "CREMA DEL CIELO", "PANNACOTA", "MASCARPONE", "CAPUCCINO", "MARROC", "OREO", "SNIKERS", "SAMBAYON", "SAMBAYON PORTOFINO"],
    frutas: ["CEREZA", "FRUTILLA CREMA", "BANANA SPLIT", "MARACUYA", "ANANA AL CHANTILLY", "FRAMBUESA C/ CHOCO", "KINOTOS AL WHISKY", "DURAZNOS AL OPORTO", "MANZANA VERDE", "LEMON PIE", "LIMON C/MARACUYA", "FRAMBUESA C/CHOCO"],
    otros: [] // El resto de los productos se asignarán automáticamente aquí
};

function mostrarVistaGrupos() {
    console.log("🔄 Mostrando vista de grupos...");

    

    tablaGeneral.classList.add("fade-out");

    setTimeout(() => {
        document.getElementById("stockTable").style.display = "none";
        tablaGeneral.classList.remove("fade-out");
        
        // Mostrar Vista de Grupos con transición suave
        document.getElementById("vistaGrupos").style.display = "flex";
        requestAnimationFrame(() => {
            vistaGrupos.classList.add("fade-in");
            setTimeout(() => vistaGrupos.classList.remove("fade-in"), 300);
        });
    }, 300);

    // Ocultar tabla general y mostrar la vista de grupos
    
    

    const gruposBody = {
        clasicos: document.getElementById("clasicos-body"),
        chocolates: document.getElementById("chocolates-body"),
        dulces: document.getElementById("dulces-body"),
        cremas: document.getElementById("cremas-body"),
        frutas: document.getElementById("frutas-body"),
        otros: document.getElementById("otros-body"),
    };

    // Limpiar contenido de las tablas antes de agregar contenido nuevo
    Object.values(gruposBody).forEach(body => body.innerHTML = "");

    // Obtener todas las filas de la tabla general
    document.querySelectorAll("#stockTable tbody tr").forEach(row => {
        const nombre = row.cells[0].textContent.trim().toUpperCase();
        const cantidad = row.cells[1].textContent.trim();

        let grupoAsignado = "otros";

        // Verificar en qué grupo está el producto
        for (const [grupo, productos] of Object.entries(grupos)) {
            if (productos.includes(nombre)) {
                grupoAsignado = grupo;
                break;
            }
        }

        // Crear fila para la tabla de grupo correspondiente
        const nuevaFila = document.createElement("tr");
        nuevaFila.innerHTML = `<td>${nombre}</td><td>${cantidad}</td>`;

        // Resaltar en rojo si el stock está por debajo del mínimo
        if (row.classList.contains("resaltar-bajo-stock")) {
            nuevaFila.classList.add("resaltar-bajo-stock");
        }

        // Insertar la fila en la tabla del grupo correspondiente
        if (gruposBody[grupoAsignado]) {
            gruposBody[grupoAsignado].appendChild(nuevaFila);
        } else {
            console.warn(`⚠️ No se encontró el contenedor para el grupo ${grupoAsignado}`);
        }
    });
}
 
function mostrarVistaGeneral() {

    console.log("🔄 Mostrando vista general...");

    // Aplicar animación de fade-out a la vista de grupos
    vistaGrupos.classList.add("fade-out");

    setTimeout(() => {
        document.getElementById("vistaGrupos").style.display = "none";
        vistaGrupos.classList.remove("fade-out");

        // Mostrar la tabla general con transición suave
        document.getElementById("stockTable").style.display = "table";
        requestAnimationFrame(() => {
            tablaGeneral.classList.add("fade-in");
            setTimeout(() => tablaGeneral.classList.remove("fade-in"), 300);
        });
    }, 300);

}

document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("botonVistaGrupos").addEventListener("click", mostrarVistaGrupos);
    document.getElementById("botonVistaGeneral").addEventListener("click", mostrarVistaGeneral);
    
});

function openMenu() {
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("overlay");

    sidebar.classList.add("open");
    overlay.classList.add("active");
}

function closeMenu() {
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("overlay");

    sidebar.classList.remove("open");
    overlay.classList.remove("active");
}

document.addEventListener("DOMContentLoaded", function () {
    const menuBtn = document.getElementById("menu-btn");
    const closeBtn = document.getElementById("close-btn");
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("overlay");

    // ✅ Evento para abrir menú
    menuBtn.addEventListener("click", function () {
        sidebar.classList.add("open");
        overlay.classList.add("active");
    });

    

    // ✅ Cerrar menú si se hace clic fuera
    overlay.addEventListener("click", function () {
        sidebar.classList.remove("open");
        overlay.classList.remove("active");
    });
});

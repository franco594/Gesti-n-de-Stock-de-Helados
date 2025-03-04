let productosEscaneados = [];
let modo = '';
let modalAbierta = false; // Controla si el escaneo está habilitado


console.log("📢 DOM completamente cargado.");

// Obtener elementos del DOM
const stockModal = document.getElementById("stockModal");
const stockTable = document.getElementById("stockTable");
const configButton = document.getElementById("configButton");
const closeModal = document.querySelector(".close");
const codigoScanner = document.getElementById("codigoScanner");

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

    document.getElementById(`modal-${tipo}`).style.display = "block";
    activarInputEscaneo(); 
    obtenerProductosEscaneados();

    setTimeout(() => {
        codigoScanner.focus();  // 🔥 Asegurar que el input tiene foco
    }, 100); 
}

// ❌ Modificar la función cerrarModal para deshabilitar el input
function cerrarModal(tipo) {
    modalAbierta = false;
    console.log(`❌ Modal cerrada: ${tipo}`);

    fetch("/api/reiniciar_lista_temporal/", { method: "POST" })
    .then(() => {
        document.getElementById(`modal-${tipo}`).style.display = "none";
        productosEscaneados = [];
        actualizarListaEscaneados(modo, []);
        desactivarInputEscaneo(); // 🔴 Desactivar el input de escaneo
        location.reload();
    })
    .catch(error => console.error("Error al reiniciar la lista:", error));
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
    
    productosEscaneados.forEach((producto, index) => {
        const item = document.createElement("li");
        item.textContent = `Balde ${index + 1}: ${producto.nombre}, Peso: ${producto.peso}g`;
        
        const botonEliminar = document.createElement("button");
        botonEliminar.classList.add("btnEliminar");
        botonEliminar.textContent = "❌";
        botonEliminar.style.cursor = "pointer";
        botonEliminar.onclick = () => eliminarProductoEscaneado(index, modalTipo);

        item.appendChild(botonEliminar);
        lista.appendChild(item);
    });
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
    setTimeout(() => {
        modal.style.display = "none";
    }, 3000); // Ocultar automáticamente después de 3 segundos
}

// ✅ Confirmar y agregar los productos escaneados al servidor
function confirmarAgregarProductos() {
    console.log("📢 Intentando confirmar productos. Lista actual:", productosEscaneados);

    if (!productosEscaneados || productosEscaneados.length === 0) {
        console.warn("⛔ No hay productos escaneados para agregar.");
        return;
    }

    const payload = { productos: productosEscaneados };
    console.log("📤 Enviando datos al backend:", JSON.stringify(payload));

    fetch('/api/confirmar_codigos/', {
        method: 'POST',
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json().catch(() => response.text())) // Intentar convertir a JSON
    .then(data => {
        console.log("🔄 Respuesta del servidor:", data);

        if (data.error) {
            console.error("❌ Error al confirmar productos:", data.error);
        } else {
            console.log("✅ Productos agregados correctamente.");
            mostrarModalConfirmacion(data.message);
            cerrarModal("ingresar");
            productosEscaneados = []; // Vaciar la lista después de confirmar
        }
    })
    .catch(error => console.error("⚠️ Error al agregar productos:", error));
}



// ✅ Confirmar y retirar productos escaneados
function confirmarRetirarProductos() {
    if (productosEscaneados.length === 0) {
        console.warn("⛔ No hay productos escaneados para retirar.");
        return;
    }

    fetch('/api/confirmar_retiro/', {
        method: 'POST',
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ productos: productosEscaneados })
    })
    .then(response => response.json())
    .then(data => {
        mostrarModalConfirmacion(data.message);
        cerrarModal("retirar");
    })
    .catch(error => console.error("❌ Error al retirar productos:", error));
};


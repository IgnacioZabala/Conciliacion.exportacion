import streamlit as st
import pdfplumber
import re

st.set_page_config(page_title="Conciliación de Exportaciones", layout="wide")

# --- LÓGICA DE ESTADO Y MEMORIA ---
if 'exportaciones' not in st.session_state:
    st.session_state['exportaciones'] = {}
if 'orden_actual' not in st.session_state:
    st.session_state['orden_actual'] = None

# --- FUNCIONES DE EXTRACCIÓN ---
def extraer_monto_usd(texto, concepto, tc_banco):
    idx = texto.upper().find(concepto.upper())
    if idx != -1:
        bloque = texto[idx:idx+150]
        numeros = re.findall(r'\b\d+\.\d+\b', bloque)
        for num_str in numeros:
            num = float(num_str)
            if 0 < num < 1000 and num != tc_banco:
                return num
    return 0.0

def procesar_pdf(archivo):
    texto_completo = ""
    with pdfplumber.open(archivo) as pdf:
        for pagina in pdf.pages:
            texto_completo += pagina.extract_text() + "\n"
    
    texto_limpio = texto_completo.replace(',', '.')
    datos = {"tipo": "Desconocido"}
    
    if "FACTURA DE EXPORTACIÓN" in texto_completo.upper():
        datos["tipo"] = "Factura"
        tc_match = re.search(r'Tipo de Cambio:\s*([\d\.]+)', texto_limpio)
        if tc_match: datos["tc_factura"] = float(tc_match.group(1))

    elif "ID SWIFT" in texto_completo.upper():
        datos["tipo"] = "Swift"
        operacion_match = re.search(r'Monto operación\s*:\s*([\d\.]+)', texto_limpio)
        
        if "ANTICIPO" in texto_completo.upper():
            datos["etiqueta"] = "Anticipo"
        else:
            datos["etiqueta"] = "Restante"
            
        if operacion_match: datos["usd_swift"] = float(operacion_match.group(1))

    elif "AVISO DE CREDITO" in texto_completo.upper():
        datos["tipo"] = "Liquidacion"
        liq_match = re.search(r'B01-COBROS DE EXPORTACIONES DE BIENES.*?USD\s*([\d\.]+)\s*([\d\.]+)', texto_limpio, re.DOTALL)
        
        if liq_match:
            usd_liq = float(liq_match.group(1))
            tc_banco = float(liq_match.group(2))
            
            datos["usd_liquidado"] = usd_liq
            datos["tc_banco"] = tc_banco
            datos["usd_comision"] = extraer_monto_usd(texto_limpio, "COMISION", tc_banco)
            datos["usd_rg2408"] = extraer_monto_usd(texto_limpio, "RG2408", tc_banco)
            datos["usd_iva"] = extraer_monto_usd(texto_limpio, "IVA 21%", tc_banco)
            
    return datos

# --- PANEL LATERAL (MEMORIA) ---
with st.sidebar:
    st.title("📁 Mis Exportaciones")
    st.markdown("---")
    
    nueva_orden = st.text_input("Número de Exportación (Ej: Exp 1)")
    if st.button("Crear Exportación", use_container_width=True):
        if nueva_orden and nueva_orden not in st.session_state['exportaciones']:
            st.session_state['exportaciones'][nueva_orden] = {
                "tc_factura": 0.0,
                "swifts": [],
                "liquidaciones": []
            }
            st.session_state['orden_actual'] = nueva_orden
            st.success("Creada.")
            st.rerun()
            
    st.markdown("---")
    st.markdown("**Exportaciones Guardadas:**")
    for orden in list(st.session_state['exportaciones'].keys()):
        if st.button(f"📂 {orden}", key=f"btn_{orden}", use_container_width=True):
            st.session_state['orden_actual'] = orden
            st.rerun()

# --- PANEL PRINCIPAL ---
if st.session_state['orden_actual']:
    orden_id = st.session_state['orden_actual']
    exp_data = st.session_state['exportaciones'][orden_id]
    
    st.title(f"Exportación: {orden_id}")
    st.markdown("Carga los PDFs correspondientes a esta exportación.")
    
    archivos = st.file_uploader("Subir archivos PDF", type="pdf", accept_multiple_files=True, key=f"uploader_{orden_id}")
    
    if st.button("Procesar Archivos", type="primary"):
        for archivo in archivos:
            datos = procesar_pdf(archivo)
            if datos["tipo"] == "Factura":
                exp_data["tc_factura"] = datos.get("tc_factura", 0.0)
            elif datos["tipo"] == "Swift":
                if "swifts" not in exp_data:
                    exp_data["swifts"] = []
                exp_data["swifts"].append(datos)
            elif datos["tipo"] == "Liquidacion":
                if "liquidaciones" not in exp_data:
                    exp_data["liquidaciones"] = []
                exp_data["liquidaciones"].append(datos)
        st.success("Archivos procesados y guardados en memoria.")
        st.rerun()

    st.divider()

    # Variables con .get() para evitar KeyErrors con datos viejos[cite: 10]
    tc_factura = exp_data.get("tc_factura", 0.0)
    swifts_guardados = exp_data.get("swifts", [])
    liquidaciones_guardadas = exp_data.get("liquidaciones", [])

    # Visualización de datos procesados
    if tc_factura > 0 and swifts_guardados:
        # Ordenar para mostrar "Anticipo" primero
        swifts_ordenados = sorted(swifts_guardados, key=lambda x: 0 if x.get("etiqueta") == "Anticipo" else 1)
        
        for swift in swifts_ordenados:
            etiqueta = swift.get("etiqueta", "Cobro")
            usd_swift = swift.get("usd_swift", 0.0)
            
            # Buscar liquidación asociada
            liq = next((l for l in liquidaciones_guardadas if abs(l.get("usd_liquidado", 0) - usd_swift) < 1.0), None)
            
            st.subheader(f"{etiqueta}:")
            st.markdown(f"**Swift** ${usd_swift:,.2f}")
            
            if liq:
                tc_banco = liq.get("tc_banco", 0.0)
                
                # Conversión de gastos a pesos
                comision_ars = liq.get("usd_comision", 0.0) * tc_banco
                rg2408_ars = liq.get("usd_rg2408", 0.0) * tc_banco
                iva_ars = liq.get("usd_iva", 0.0) * tc_banco
                
                # Resultado financiero
                brecha = tc_banco - tc_factura
                resultado_ars = usd_swift * brecha
                
                if resultado_ars > 0:
                    texto_resultado = f"positivo (${resultado_ars:,.2f} ARS)"
                elif resultado_ars < 0:
                    texto_resultado = f"negativo (${resultado_ars:,.2f} ARS)"
                else:
                    texto_resultado = "neutro ($0.00 ARS)"

                st.markdown(f"**Comision** ${comision_ars:,.2f}")
                st.markdown(f"**rg2408** ${rg2408_ars:,.2f}")
                st.markdown(f"**IVA** ${iva_ars:,.2f}")
                st.markdown(f"**Resultado financiero** ({texto_resultado})")
            else:
                st.warning("*(Falta cargar el Aviso de Crédito correspondiente)*")
            
            st.write("")
            
    elif not tc_factura:
        st.info("💡 Asegúrate de cargar la Factura de Exportación.")
else:
    st.info("👈 Crea o selecciona una exportación en el panel lateral.")

import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# Configuración de página
st.set_page_config(page_title="Coopagro - Conciliación Comex", layout="wide", initial_sidebar_state="expanded")

# Inicialización del estado de la aplicación
if 'exportaciones' not in st.session_state:
    st.session_state['exportaciones'] = {}
if 'orden_actual' not in st.session_state:
    st.session_state['orden_actual'] = None

# --- FUNCIONES DE EXTRACCIÓN DE PDF ---
def procesar_pdf(archivo):
    texto_completo = ""
    with pdfplumber.open(archivo) as pdf:
        for pagina in pdf.pages:
            texto_completo += pagina.extract_text() + "\n"
    
    datos = {"tipo": "Desconocido"}
    
    # Detección y extracción de Factura de Exportación
    if "FACTURA DE EXPORTACIÓN" in texto_completo.upper():
        datos["tipo"] = "Factura"
        nro_match = re.search(r'Compr\. Nro:\s*([\d\-]+)', texto_completo)
        total_match = re.search(r'Importe Total:\s*USD\s*([\d\,\.]+)', texto_completo)
        tc_match = re.search(r'Tipo de Cambio:\s*([\d\,\.]+)', texto_completo)
        
        if nro_match: datos["nro_factura"] = nro_match.group(1)
        if total_match: datos["total_usd"] = float(total_match.group(1).replace('.', '').replace(',', '.'))
        if tc_match: datos["tc_factura"] = float(tc_match.group(1).replace('.', '').replace(',', '.'))

    # Detección y extracción de SWIFT
    elif "ID SWIFT" in texto_completo.upper():
        datos["tipo"] = "Swift"
        ref_match = re.search(r'REFERENCIA:\s*(\w+)', texto_completo)
        instruido_match = re.search(r'Importe instruido\s*:\s*([\d\,\.]+)', texto_completo)
        operacion_match = re.search(r'Monto operación\s*:\s*([\d\,\.]+)', texto_completo)
        
        if ref_match: datos["referencia"] = ref_match.group(1)
        if instruido_match: datos["usd_instruido"] = float(instruido_match.group(1).replace(',', '.'))
        if operacion_match: datos["usd_operacion"] = float(operacion_match.group(1).replace(',', '.'))

    # Detección y extracción de Liquidación Bancaria (Aviso de Crédito)
    elif "AVISO DE CREDITO" in texto_completo.upper():
        datos["tipo"] = "Liquidacion"
        orden_match = re.search(r'ORDEN DE PAGO:\s*(\w+)', texto_completo)
        # Busca el bloque de liquidación específico para extraer monto y TC
        liq_match = re.search(r'B01-COBROS DE EXPORTACIONES DE BIENES.*?USD\s*([\d\.]+)\s*([\d\.]+)', texto_completo, re.DOTALL)
        
        if orden_match: datos["orden_pago"] = orden_match.group(1)
        if liq_match:
            datos["usd_liquidado"] = float(liq_match.group(1))
            datos["tc_banco"] = float(liq_match.group(2))
            
    return datos

# --- INTERFAZ DE USUARIO ---

# 1. Panel Izquierdo (Sidebar)
with st.sidebar:
    st.image("https://img.icons8.com/color/96/000000/export.png", width=60) # Placeholder logo
    st.title("Gestión de Exportaciones")
    
    # Crear nueva orden
    st.markdown("### Nueva Orden")
    nueva_orden = st.text_input("Nro de Exportación / Factura")
    if st.button("Crear Carpeta", use_container_width=True):
        if nueva_orden and nueva_orden not in st.session_state['exportaciones']:
            st.session_state['exportaciones'][nueva_orden] = {
                "factura": {},
                "swifts": [],
                "liquidaciones": []
            }
            st.session_state['orden_actual'] = nueva_orden
            st.success("Carpeta creada.")
            st.rerun()

    st.divider()
    st.markdown("### Órdenes Activas")
    
    # Listar órdenes y su estado
    for orden, data in st.session_state['exportaciones'].items():
        # Calcular progreso
        total_factura = data['factura'].get('total_usd', 0)
        total_cobrado = sum(s.get('usd_instruido', 0) for s in data['swifts'])
        
        estado = "🔴 Sin datos"
        if total_factura > 0:
            if abs(total_factura - total_cobrado) < 1.0: # Margen de tolerancia de 1 USD
                estado = "🟢 100% Cerrada"
            elif total_cobrado > 0:
                estado = f"🟡 Parcial ({(total_cobrado/total_factura)*100:.0f}%)"
            else:
                estado = "🔴 Pendiente cobro"
                
        if st.button(f"{orden}\n{estado}", key=orden, use_container_width=True):
            st.session_state['orden_actual'] = orden
            st.rerun()

# 2. Panel Central
if st.session_state['orden_actual']:
    orden_id = st.session_state['orden_actual']
    exp_data = st.session_state['exportaciones'][orden_id]
    
    st.header(f"Exportación: {orden_id}")
    
    # Subida de archivos
    st.markdown("#### Cargar Comprobantes (Factura, Swift, Liquidaciones)")
    archivos_subidos = st.file_uploader("Arrastra los PDFs aquí", type="pdf", accept_multiple_files=True)
    
    if st.button("Procesar Archivos", type="primary"):
        for archivo in archivos_subidos:
            datos_extraidos = procesar_pdf(archivo)
            
            if datos_extraidos["tipo"] == "Factura":
                exp_data["factura"] = datos_extraidos
            elif datos_extraidos["tipo"] == "Swift":
                # Evitar duplicados por referencia
                if not any(s.get('referencia') == datos_extraidos.get('referencia') for s in exp_data["swifts"]):
                    exp_data["swifts"].append(datos_extraidos)
            elif datos_extraidos["tipo"] == "Liquidacion":
                if not any(l.get('orden_pago') == datos_extraidos.get('orden_pago') for l in exp_data["liquidaciones"]):
                    exp_data["liquidaciones"].append(datos_extraidos)
        
        st.success("Archivos procesados e incorporados a la orden.")
        st.rerun()

    st.divider()

    # Dashboard de Conciliación
    col1, col2, col3 = st.columns(3)
    
    total_factura = exp_data['factura'].get('total_usd', 0.0)
    tc_factura = exp_data['factura'].get('tc_factura', 0.0)
    total_instruido = sum(s.get('usd_instruido', 0.0) for s in exp_data["swifts"])
    saldo_pendiente = total_factura - total_instruido

    col1.metric("Total Facturado (USD)", f"${total_factura:,.2f}", f"TC BNA: {tc_factura}")
    col2.metric("Total Instruido Recibido (USD)", f"${total_instruido:,.2f}")
    col3.metric("Saldo Pendiente (USD)", f"${saldo_pendiente:,.2f}", 
                delta="Cerrada" if saldo_pendiente == 0 else "Pendiente", 
                delta_color="normal" if saldo_pendiente == 0 else "inverse")

    # Detalle Financiero y Diferencia de Cambio
    st.markdown("### Resultado Financiero por Liquidaciones")
    
    if exp_data["liquidaciones"]:
        resultados = []
        for liq in exp_data["liquidaciones"]:
            usd_liq = liq.get('usd_liquidado', 0)
            tc_banco = liq.get('tc_banco', 0)
            dif_tc = tc_banco - tc_factura
            resultado_ars = usd_liq * dif_tc
            
            resultados.append({
                "Orden de Pago": liq.get('orden_pago', 'N/A'),
                "Monto Liquidado (USD)": usd_liq,
                "TC Banco": tc_banco,
                "TC Factura": tc_factura,
                "Brecha TC": dif_tc,
                "Resultado Financiero (ARS)": resultado_ars
            })
            
        df_resultados = pd.DataFrame(resultados)
        
        # st.dataframe permite visualización limpia
        st.dataframe(df_resultados.style.format({
            "Monto Liquidado (USD)": "${:,.2f}",
            "TC Banco": "{:,.2f}",
            "TC Factura": "{:,.2f}",
            "Brecha TC": "{:,.2f}",
            "Resultado Financiero (ARS)": "${:,.2f}"
        }), use_container_width=True)
        
        resultado_total = df_resultados["Resultado Financiero (ARS)"].sum()
        if resultado_total > 0:
            st.success(f"**Ganancia Total por Diferencia de Cambio:** ${resultado_total:,.2f} ARS")
        else:
            st.error(f"**Pérdida Total por Diferencia de Cambio:** ${resultado_total:,.2f} ARS")
    else:
        st.info("No se han cargado liquidaciones bancarias para calcular el resultado financiero.")

else:
    st.info("Crea o selecciona una orden en el panel izquierdo para comenzar.")

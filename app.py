import streamlit as st
import pandas as pd
import pdfplumber
import re

# Configuración de página profesional
st.set_page_config(page_title="Coopagro - Conciliación Comex", layout="wide", initial_sidebar_state="expanded")

# Inicialización del estado
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
    
    datos = {"tipo": "Desconocido", "archivo": archivo.name}
    
    # 1. Factura de Exportación
    if "FACTURA DE EXPORTACIÓN" in texto_completo.upper():
        datos["tipo"] = "Factura"
        nro_match = re.search(r'Compr\. Nro:\s*([\d\-]+)', texto_completo)
        # Corrección del parseo decimal: solo reemplazar coma por punto
        total_match = re.search(r'Importe Total:\s*USD\s*([\d\.]+)', texto_completo.replace(',', '.'))
        tc_match = re.search(r'Tipo de Cambio:\s*([\d\.]+)', texto_completo.replace(',', '.'))
        
        if nro_match: datos["nro_factura"] = nro_match.group(1)
        if total_match: datos["total_usd"] = float(total_match.group(1))
        if tc_match: datos["tc_factura"] = float(tc_match.group(1))

    # 2. Mensaje SWIFT
    elif "ID SWIFT" in texto_completo.upper():
        datos["tipo"] = "Swift"
        ref_match = re.search(r'REFERENCIA:\s*(\w+)', texto_completo)
        instruido_match = re.search(r'Importe instruido\s*:\s*([\d\.]+)', texto_completo.replace(',', '.'))
        operacion_match = re.search(r'Monto operación\s*:\s*([\d\.]+)', texto_completo.replace(',', '.'))
        gastos_match = re.search(r'Gastos de transacción.*:\s*([\d\.]+)', texto_completo.replace(',', '.'))
        
        if ref_match: datos["referencia"] = ref_match.group(1)
        if instruido_match: datos["usd_instruido"] = float(instruido_match.group(1))
        if operacion_match: datos["usd_operacion"] = float(operacion_match.group(1)) # Monto neto recibido
        if gastos_match: datos["usd_gastos_swift"] = float(gastos_match.group(1))

    # 3. Liquidación Bancaria
    elif "AVISO DE CREDITO" in texto_completo.upper():
        datos["tipo"] = "Liquidacion"
        orden_match = re.search(r'ORDEN DE PAGO:\s*(\w+)', texto_completo)
        
        # Extracción de montos (adaptado a Santander)
        texto_limpio = texto_completo.replace(',', '.')
        liq_match = re.search(r'B01-COBROS DE EXPORTACIONES DE BIENES.*?USD\s*([\d\.]+)\s*([\d\.]+)', texto_limpio, re.DOTALL)
        
        # Búsqueda aproximada de Comisiones e IVA (asumiendo formato estándar)
        comision_match = re.search(r'COMISION.*?USD\s*(?:\|\s*)?([\d\.]+)', texto_limpio, re.DOTALL)
        iva_match = re.search(r'IVA 21%.*?USD\s*(?:\|\s*)?([\d\.]+)', texto_limpio, re.DOTALL)
        
        if orden_match: datos["orden_pago"] = orden_match.group(1)
        if liq_match:
            datos["usd_liquidado"] = float(liq_match.group(1))
            datos["tc_banco"] = float(liq_match.group(2))
        if comision_match: datos["usd_comision"] = float(comision_match.group(1))
        else: datos["usd_comision"] = 0.0
        if iva_match: datos["usd_iva"] = float(iva_match.group(1))
        else: datos["usd_iva"] = 0.0
            
    return datos

# --- INTERFAZ DE USUARIO ---

with st.sidebar:
    st.title("🏦 Comex | Coopagro")
    st.markdown("---")
    
    st.markdown("### Nueva Operación")
    nueva_orden = st.text_input("Referencia (Ej: Factura 0015)")
    if st.button("Crear Expediente", use_container_width=True):
        if nueva_orden and nueva_orden not in st.session_state['exportaciones']:
            st.session_state['exportaciones'][nueva_orden] = {"factura": {}, "swifts": [], "liquidaciones": []}
            st.session_state['orden_actual'] = nueva_orden
            st.success("Expediente creado.")
            st.rerun()

    st.markdown("---")
    st.markdown("### Expedientes Activos")
    
    for orden, data in st.session_state['exportaciones'].items():
        total_factura = data['factura'].get('total_usd', 0)
        total_cobrado = sum(s.get('usd_instruido', 0) for s in data['swifts'])
        
        estado = "🔴 Pendiente"
        if total_factura > 0:
            if abs(total_factura - total_cobrado) < 1.0:
                estado = "🟢 100% Cerrada"
            elif total_cobrado > 0:
                estado = f"🟡 Parcial ({(total_cobrado/total_factura)*100:.0f}%)"
                
        if st.button(f"{orden} | {estado}", key=orden, use_container_width=True):
            st.session_state['orden_actual'] = orden
            st.rerun()

# Panel Principal
if st.session_state['orden_actual']:
    orden_id = st.session_state['orden_actual']
    exp_data = st.session_state['exportaciones'][orden_id]
    
    st.header(f"Expediente: {orden_id}")
    
    # Uploader
    with st.expander("📥 Cargar Documentación (PDF)", expanded=True):
        archivos_subidos = st.file_uploader("Adjunte Factura, Swifts y Avisos de Crédito", type="pdf", accept_multiple_files=True)
        if st.button("Procesar Documentos", type="primary"):
            for archivo in archivos_subidos:
                datos = procesar_pdf(archivo)
                if datos["tipo"] == "Factura":
                    exp_data["factura"] = datos
                elif datos["tipo"] == "Swift":
                    if not any(s.get('referencia') == datos.get('referencia') for s in exp_data["swifts"]):
                        exp_data["swifts"].append(datos)
                elif datos["tipo"] == "Liquidacion":
                    if not any(l.get('orden_pago') == datos.get('orden_pago') for l in exp_data["liquidaciones"]):
                        exp_data["liquidaciones"].append(datos)
            st.rerun()

    st.markdown("---")

    # Métricas Principales (Sin indicadores delta)
    col1, col2, col3 = st.columns(3)
    total_factura = exp_data['factura'].get('total_usd', 0.0)
    tc_factura = exp_data['factura'].get('tc_factura', 0.0)
    total_instruido = sum(s.get('usd_instruido', 0.0) for s in exp_data["swifts"])
    saldo_pendiente = total_factura - total_instruido

    with col1:
        st.metric("Total Facturado (USD)", f"${total_factura:,.2f}")
        if tc_factura:
            st.caption(f"Tipo de Cambio BNA: **${tc_factura:,.2f}**")
    with col2:
        st.metric("Total Instruido Recibido (USD)", f"${total_instruido:,.2f}")
    with col3:
        st.metric("Saldo Pendiente (USD)", f"${saldo_pendiente:,.2f}")

    st.markdown("---")

    # Desglose Profesional por Cobro
    st.subheader("📑 Detalle Analítico de Cobros")
    
    if exp_data["swifts"]:
        for i, swift in enumerate(exp_data["swifts"]):
            # Intentar emparejar el Swift con su liquidación (asumiendo mismo orden de carga o monto neto)
            # Se empareja por monto neto de operación (USD liquidado)
            usd_neto_swift = swift.get('usd_operacion', 0)
            liq_asociada = next((l for l in exp_data["liquidaciones"] if abs(l.get('usd_liquidado', 0) - usd_neto_swift) < 1.0), None)
            
            with st.container(border=True):
                st.markdown(f"#### Etapa de Cobro {i+1}: Swift Ref. {swift.get('referencia', 'S/D')}")
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Importe Instruido (Bruto)", f"USD {swift.get('usd_instruido', 0):,.2f}")
                c2.metric("Gastos Corresponsal", f"USD {swift.get('usd_gastos_swift', 0):,.2f}")
                c3.metric("Monto Neto a Liquidar", f"USD {usd_neto_swift:,.2f}")
                
                if liq_asociada:
                    tc_banco = liq_asociada.get('tc_banco', 0)
                    brecha = tc_banco - tc_factura
                    res_financiero = usd_neto_swift * brecha
                    
                    c4.metric("TC Banco Liquidado", f"${tc_banco:,.2f}")
                    
                    st.markdown("**Desglose Bancario (Liquidación Orden {}):**".format(liq_asociada.get('orden_pago', 'S/D')))
                    
                    # Tabla de detalle estructurada
                    detalle_df = pd.DataFrame([{
                        "Concepto": "Comisión Bancaria", "Moneda": "USD", "Monto": liq_asociada.get('usd_comision', 0)
                    }, {
                        "Concepto": "IVA sobre Comisión", "Moneda": "USD", "Monto": liq_asociada.get('usd_iva', 0)
                    }, {
                        "Concepto": "Resultado Financiero", "Moneda": "ARS", "Monto": res_financiero
                    }])
                    
                    st.dataframe(
                        detalle_df,
                        column_config={
                            "Monto": st.column_config.NumberColumn("Monto", format="%.2f")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    if res_financiero > 0:
                        st.success(f"📈 Resultado Financiero Positivo: **ARS ${res_financiero:,.2f}** (Brecha TC: ${brecha:,.2f})")
                    else:
                        st.error(f"📉 Resultado Financiero Negativo: **ARS ${res_financiero:,.2f}** (Brecha TC: ${brecha:,.2f})")
                else:
                    c4.warning("Liquidación bancaria pendiente de carga.")
    else:
        st.info("Aún no se han cargado cobros (Swifts) para esta operación.")

else:
    st.info("👈 Seleccione o cree un expediente en el panel lateral para comenzar.")

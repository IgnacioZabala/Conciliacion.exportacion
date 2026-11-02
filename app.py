import streamlit as st
import pdfplumber
import re
import pandas as pd

st.set_page_config(page_title="Liquidación de Exportación", layout="wide")

def extraer_datos_factura(pdf_file):
    datos = {
        "cliente": "",
        "numero_factura": "",
        "fecha": "",
        "importe_usd": 0.0,
        "tc": 0.0,
        "kilos": 0.0
    }
    
    try:
        with pdfplumber.open(pdf_file) as pdf:
            texto = ""
            for page in pdf.pages:
                texto += page.extract_text() + "\n"
            
            # Expresiones regulares ajustadas para Factura E de AFIP
            match_cliente = re.search(r'Señor\(es\):\s*(.*?)\n', texto)
            match_factura = re.search(r'Punto de Venta:\s*(\d{4,5})\s*Comp\. Nro:\s*(\d{8})', texto)
            match_fecha = re.search(r'Fecha de Emisión:\s*(\d{2}/\d{2}/\d{4})', texto)
            match_importe = re.search(r'Importe Total:\s*(?:USD|U\$S)?\s*([\d\.,]+)', texto)
            match_tc = re.search(r'Tipo de Cambio:\s*([\d\.,]+)', texto)
            
            if match_cliente: datos["cliente"] = match_cliente.group(1).strip()
            if match_factura: datos["numero_factura"] = f"{int(match_factura.group(1)):05d}-{int(match_factura.group(2)):08d}"
            if match_fecha: datos["fecha"] = match_fecha.group(1)
            if match_importe: datos["importe_usd"] = float(match_importe.group(1).replace('.', '').replace(',', '.'))
            if match_tc: datos["tc"] = float(match_tc.group(1).replace('.', '').replace(',', '.'))
            
    except Exception as e:
        st.warning(f"No se pudieron extraer todos los datos automáticamente: {e}")
        
    return datos

st.title("Gestión de Cobros y Liquidación de Divisas")

st.markdown("### 1. Documentación de Exportación")
archivo_pdf = st.file_uploader("Adjuntar Factura E (PDF)", type=["pdf"])

datos_por_defecto = {"cliente": "", "numero_factura": "", "fecha": "", "importe_usd": 0.0, "tc": 0.0, "kilos": 0.0}

if archivo_pdf is not None:
    with st.spinner("Procesando documento..."):
        datos_por_defecto = extraer_datos_factura(archivo_pdf)

# Formulario de verificación de datos extraídos
with st.form("datos_factura"):
    col1, col2, col3 = st.columns(3)
    cliente = col1.text_input("Cliente", value=datos_por_defecto["cliente"])
    n_factura = col2.text_input("N° Factura E", value=datos_por_defecto["numero_factura"], help="Formato 00000-00000000")
    fecha = col3.text_input("Fecha", value=datos_por_defecto["fecha"])
    
    col4, col5, col6 = st.columns(3)
    importe_total = col4.number_input("Importe total (USD)", value=datos_por_defecto["importe_usd"], step=100.0)
    tc_factura = col5.number_input("T.C. factura", value=datos_por_defecto["tc"], format="%.4f")
    kilos_prod = col6.number_input("Kilos de producto", value=datos_por_defecto["kilos"], step=10.0)
    
    confirmar_datos = st.form_submit_button("Confirmar Datos de Factura")

st.divider()

st.markdown("### 2. Conciliación Bancaria y Liquidación")
# Pestañas para dividir el flujo de caja
tab_anticipo, tab_restante, tab_resumen = st.tabs(["Ingreso Anticipo", "Ingreso Restante", "Resumen Final"])

def calcular_neto(monto, swift, comision, iva, tc):
    gastos_usd = swift + comision + iva
    neto_usd = monto - gastos_usd
    neto_ars = neto_usd * tc
    return gastos_usd, neto_usd, neto_ars

with tab_anticipo:
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        monto_anticipo = st.number_input("Monto Bruto Recibido (USD) - Anticipo", min_value=0.0, step=100.0)
        tc_anticipo = st.number_input("Tipo de Cambio Liquidación Anticipo", min_value=0.0, format="%.2f")
    with col_a2:
        swift_anticipo = st.number_input("Gastos SWIFT (USD) - Anticipo", min_value=0.0, step=10.0)
        comision_anticipo = st.number_input("Comisión Bancaria (USD) - Anticipo", min_value=0.0, step=10.0)
        iva_anticipo = st.number_input("IVA sobre Comisiones (USD) - Anticipo", min_value=0.0, step=5.0)

with tab_restante:
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        monto_restante = st.number_input("Monto Bruto Recibido (USD) - Restante", value=float(importe_total - monto_anticipo), min_value=0.0, step=100.0)
        tc_restante = st.number_input("Tipo de Cambio Liquidación Restante", min_value=0.0, format="%.2f")
    with col_r2:
        swift_restante = st.number_input("Gastos SWIFT (USD) - Restante", min_value=0.0, step=10.0)
        comision_restante = st.number_input("Comisión Bancaria (USD) - Restante", min_value=0.0, step=10.0)
        iva_restante = st.number_input("IVA sobre Comisiones (USD) - Restante", min_value=0.0, step=5.0)

with tab_resumen:
    gastos_ant, neto_usd_ant, neto_ars_ant = calcular_neto(monto_anticipo, swift_anticipo, comision_anticipo, iva_anticipo, tc_anticipo)
    gastos_rest, neto_usd_rest, neto_ars_rest = calcular_neto(monto_restante, swift_restante, comision_restante, iva_restante, tc_restante)
    
    st.markdown("#### Desglose de Operación")
    
    df_resumen = pd.DataFrame({
        "Concepto": ["Anticipo", "Restante", "TOTAL"],
        "Ingreso Bruto (USD)": [monto_anticipo, monto_restante, monto_anticipo + monto_restante],
        "Gastos Bancarios (USD)": [gastos_ant, gastos_rest, gastos_ant + gastos_rest],
        "Liquidación Neta (USD)": [neto_usd_ant, neto_usd_rest, neto_usd_ant + neto_usd_rest],
        "Liquidación Neta (ARS)": [neto_ars_ant, neto_ars_rest, neto_ars_ant + neto_ars_rest]
    })
    
    st.dataframe(df_resumen.style.format({
        "Ingreso Bruto (USD)": "${:,.2f}",
        "Gastos Bancarios (USD)": "${:,.2f}",
        "Liquidación Neta (USD)": "${:,.2f}",
        "Liquidación Neta (ARS)": "${:,.2f}"
    }), use_container_width=True)
    
    if (monto_anticipo + monto_restante) > importe_total:
        st.error(f"⚠️ El monto cobrado ({monto_anticipo + monto_restante} USD) supera el total de la factura ({importe_total} USD).")

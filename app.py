import streamlit as st
import pdfplumber
import re
import pandas as pd

st.set_page_config(page_title="Conciliador de Exportaciones", layout="wide")

def extract_factura_data(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text()
    
    # Buscar importe total y tipo de cambio
    total_match = re.search(r'Importe Total:\s*USD\s*([\d.,]+)', text)
    tc_match = re.search(r'Tipo de Cambio:\s*([\d.,]+)', text)
    
    total_usd = float(total_match.group(1).replace('.', '').replace(',', '.')) if total_match else 0.0
    tc_factura = float(tc_match.group(1).replace('.', '').replace(',', '.')) if tc_match else 0.0
    
    return total_usd, tc_factura

def extract_swift_data(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text()
            
    # Buscar monto instruido, monto operacion y gastos
    instruido_match = re.search(r'Importe instruido\s*:\s*([\d.,]+)', text)
    operacion_match = re.search(r'Monto operación\s*:\s*([\d.,]+)', text)
    
    # Sumar todos los gastos a cargo del portador
    gastos = re.findall(r'Gastos de transacción a cargo del portador.*:\s*([\d.,]+)', text)
    total_gastos = sum([float(g.replace('.', '').replace(',', '.')) for g in gastos])
    
    importe_instruido = float(instruido_match.group(1).replace('.', '').replace(',', '.')) if instruido_match else 0.0
    monto_recibido = float(operacion_match.group(1).replace('.', '').replace(',', '.')) if operacion_match else 0.0
    
    return importe_instruido, monto_recibido, total_gastos

def extract_liquidacion_data(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text()
            
    # Buscar TC de liquidación y comisiones locales
    tc_liq_match = re.search(r'SUBTOTAL POR TRANSF\s+USD\s+[\d.,]+\s+([\d.,]+)', text)
    
    comision = re.search(r'COMISION\s+USD\s+([\d.,]+)', text)
    rg = re.search(r'RG2408\s+USD\s+([\d.,]+)', text)
    iva = re.search(r'IVA 21%.*\s+USD\s+([\d.,]+)', text)
    
    tc_liq = float(tc_liq_match.group(1).replace('.', '').replace(',', '.')) if tc_liq_match else 0.0
    
    total_comisiones_locales = 0.0
    for val in [comision, rg, iva]:
        if val:
            total_comisiones_locales += float(val.group(1).replace('.', '').replace(',', '.'))
            
    return tc_liq, total_comisiones_locales

# --- Interfaz de Usuario ---
st.title("📊 Conciliador de Cobros de Exportación")
st.markdown("Sube los tres documentos correspondientes al despacho para generar el reporte de conciliación cambiaria y financiera.")

col1, col2, col3 = st.columns(3)
with col1:
    file_factura = st.file_uploader("1. Factura de Exportación (PDF)", type="pdf")
with col2:
    file_swift = st.file_uploader("2. Mensaje SWIFT (PDF)", type="pdf")
with col3:
    file_liq = st.file_uploader("3. Aviso de Crédito / Comisiones (PDF)", type="pdf")

if file_factura and file_swift and file_liq:
    st.divider()
    
    # Extracción
    factura_usd, tc_factura = extract_factura_data(file_factura)
    swift_instruido, swift_recibido, swift_gastos = extract_swift_data(file_swift)
    tc_liq, comisiones_locales = extract_liquidacion_data(file_liq)
    
    # Cálculos Financieros
    diferencia_cobro = factura_usd - swift_instruido
    brecha_tc = tc_liq - tc_factura
    resultado_financiero_ars = swift_recibido * brecha_tc
    
    st.subheader("📋 Resumen de la Operación")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Importe Factura", f"USD {factura_usd:,.2f}")
    m2.metric("Pago Instruido (SWIFT)", f"USD {swift_instruido:,.2f}", f"Dif: USD {-diferencia_cobro:,.2f}" if diferencia_cobro != 0 else "Cobrado 100%")
    m3.metric("Gastos SWIFT (Corresponsales)", f"USD {swift_gastos:,.2f}")
    m4.metric("Neto Liquidado", f"USD {swift_recibido:,.2f}")
    
    st.divider()
    st.subheader("💱 Análisis de Tipo de Cambio y Resultado")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("TC Factura (Cierre)", f"$ {tc_factura:,.2f}")
    c2.metric("TC Liquidación", f"$ {tc_liq:,.2f}", f"$ {brecha_tc:,.2f}")
    
    color_resultado = "normal" if resultado_financiero_ars > 0 else "inverse"
    c3.metric("Resultado por Diferencia de Cambio", f"ARS {resultado_financiero_ars:,.2f}", delta=f"ARS {resultado_financiero_ars:,.2f}", delta_color=color_resultado)
    
    st.markdown("### 🏦 Detalle de Comisiones Bancarias Locales")
    st.info(f"El banco local retuvo un total de **USD {comisiones_locales:,.2f}** en concepto de comisiones, IVA y percepciones.")

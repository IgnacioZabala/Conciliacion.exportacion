import streamlit as st
import pdfplumber
import re
import json
import os
from fpdf import FPDF

st.set_page_config(page_title="Conciliación de Exportaciones", layout="wide")

# --- ARCHIVO DE BASE DE DATOS LOCAL ---
DB_FILE = "db_exportaciones.json"

def cargar_datos():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def guardar_datos(datos):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4)

# --- FORMATO ARGENTINO ---
def formato_arg(numero):
    """Convierte 1234.56 a '1.234,56'"""
    s = f"{numero:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

# --- LÓGICA DE ESTADO Y MEMORIA ---
if 'exportaciones' not in st.session_state:
    st.session_state['exportaciones'] = cargar_datos()
if 'orden_actual' not in st.session_state:
    st.session_state['orden_actual'] = None

# --- FUNCIONES DE EXTRACCIÓN ---
def extraer_monto_usd(texto, concepto, tc_banco):
    idx = texto.upper().find(concepto.upper())
    if idx != -1:
        bloque = texto[idx:idx+400]
        numeros = re.findall(r'\b\d+\.\d{1,2}\b', bloque)
        for num_str in numeros:
            num = float(num_str)
            if 0 < num < 1000 and num != tc_banco and num != 21.0:
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
        nro_match = re.search(r'Compr\. Nro:\s*([\d\-]+)', texto_completo)
        fecha_match = re.search(r'Fecha de Emisión:\s*([\d\/]+)', texto_completo)
        cliente_match = re.search(r'Señor\(es\):\s*(.+)', texto_completo)
        tc_match = re.search(r'Tipo de Cambio:\s*([\d\.]+)', texto_limpio)
        total_match = re.search(r'Importe Total:\s*USD\s*([\d\.]+)', texto_limpio)
        
        if nro_match: datos["nro_factura"] = nro_match.group(1).strip()
        if fecha_match: datos["fecha"] = fecha_match.group(1).strip()
        if cliente_match: datos["cliente"] = cliente_match.group(1).strip()
        if tc_match: datos["tc_factura"] = float(tc_match.group(1))
        if total_match: datos["total_usd"] = float(total_match.group(1))

    elif "ID SWIFT" in texto_completo.upper():
        datos["tipo"] = "Swift"
        operacion_match = re.search(r'Monto operación\s*:\s*([\d\.]+)', texto_limpio)
        gastos_match = re.search(r'Gastos de transacci.n.*?:\s*([\d\.]+)', texto_limpio, re.IGNORECASE)
        
        if "ANTICIPO" in texto_completo.upper():
            datos["etiqueta"] = "Anticipo"
        else:
            datos["etiqueta"] = "Restante"
            
        if operacion_match: datos["usd_swift"] = float(operacion_match.group(1))
        if gastos_match: datos["gastos_swift"] = float(gastos_match.group(1))

    elif "AVISO DE CREDITO" in texto_completo.upper():
        datos["tipo"] = "Liquidacion"
        liq_match = re.search(r'B01-COBROS DE EXPORTACIONES DE BIENES.*?USD\s*([\d\.]+)\s*([\d\.]+)', texto_limpio, re.DOTALL)
        
        if liq_match:
            datos["usd_liquidado"] = float(liq_match.group(1))
            tc_banco = float(liq_match.group(2))
            datos["tc_banco"] = tc_banco
            datos["usd_comision"] = extraer_monto_usd(texto_limpio, "COMISION", tc_banco)
            datos["usd_rg2408"] = extraer_monto_usd(texto_limpio, "RG2408", tc_banco)
            datos["usd_iva"] = extraer_monto_usd(texto_limpio, "IVA 21%", tc_banco)
            
    return datos

# --- FUNCIÓN GENERADORA DE PDF PARA IMPRESIÓN ---
def generar_pdf_impresion(orden_id, exp_data):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, txt=f"Conciliacion de Exportacion: {orden_id}", ln=True, align="C")
    pdf.ln(5)

    # Datos Factura
    datos_factura = exp_data.get("factura", {})
    tc_factura = datos_factura.get("tc_factura", 0.0)
    total_factura_usd = datos_factura.get('total_usd', 0.0)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, txt="Datos de la Factura", ln=True)
    pdf.set_font("helvetica", "", 10)
    
    cliente = datos_factura.get('cliente', 'S/D').encode('latin-1', 'replace').decode('latin-1')
    pdf.cell(0, 6, txt=f"Fecha: {datos_factura.get('fecha', 'S/D')} | Nro: {datos_factura.get('nro_factura', 'S/D')}", ln=True)
    pdf.cell(0, 6, txt=f"Cliente: {cliente}", ln=True)
    pdf.cell(0, 6, txt=f"Monto: USD ${formato_arg(total_factura_usd)} | Tipo de Cambio (BNA): {formato_arg(tc_factura)}", ln=True)
    pdf.line(10, pdf.get_y()+2, 200, pdf.get_y()+2)
    pdf.ln(8)

    swifts_guardados = exp_data.get("swifts", [])
    liquidaciones_guardadas = exp_data.get("liquidaciones", [])
    swifts_ordenados = sorted(swifts_guardados, key=lambda x: 0 if x.get("etiqueta") == "Anticipo" else 1)

    for swift in swifts_ordenados:
        etiqueta = swift.get("etiqueta", "Cobro")
        usd_swift = swift.get("usd_swift", 0.0)
        gastos_swift = swift.get("gastos_swift", 0.0)
        
        liq = next((l for l in liquidaciones_guardadas if abs(l.get("usd_liquidado", 0) - usd_swift) < 1.0), None)
        
        y_start = pdf.get_y()
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(115, 8, txt=f"{etiqueta}:", ln=True)
        pdf.set_font("helvetica", "", 10)
        
        if liq:
            tc_banco = liq.get("tc_banco", 0.0)
            swift_ars = usd_swift * tc_banco
            gastos_swift_ars = gastos_swift * tc_banco
            comision_ars = liq.get("usd_comision", 0.0) * tc_banco
            rg2408_ars = liq.get("usd_rg2408", 0.0) * tc_banco
            iva_ars = liq.get("usd_iva", 0.0) * tc_banco
            
            brecha = tc_banco - tc_factura
            resultado_ars = usd_swift * brecha
            
            if resultado_ars < 0:
                txt_res = f"-${formato_arg(abs(resultado_ars))} ARS"
            else:
                txt_res = f"${formato_arg(resultado_ars)} ARS"

            pdf.cell(115, 6, txt=f"Swift (Operacion): ${formato_arg(swift_ars)} ARS", ln=True)
            pdf.cell(115, 6, txt=f"Gastos de Transaccion: ${formato_arg(gastos_swift_ars)} ARS", ln=True)
            pdf.cell(115, 6, txt=f"Comision: ${formato_arg(comision_ars)} ARS", ln=True)
            pdf.cell(115, 6, txt=f"RG2408: ${formato_arg(rg2408_ars)} ARS", ln=True)
            pdf.cell(115, 6, txt=f"IVA 21%: ${formato_arg(iva_ars)} ARS", ln=True)
            pdf.cell(115, 6, txt=f"Resultado financiero: {txt_res}", ln=True)
        else:
            pdf.cell(115, 6, txt=f"Swift (Operacion): USD ${formato_arg(usd_swift)}", ln=True)
            pdf.cell(115, 6, txt=f"Gastos de Transaccion: USD ${formato_arg(gastos_swift)}", ln=True)
            pdf.cell(115, 6, txt="(Falta cargar el Aviso de Credito para pesificar)", ln=True)

        # SELLO CONTABLE (Sin el 20)
        x_sello = 130
        w_sello = 70
        h_sello = 32
        
        pdf.rect(x_sello, y_start, w_sello, h_sello)
        pdf.set_xy(x_sello, y_start + 3)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(w_sello, 6, txt="CONTABILIZADO", align="C", ln=True)
        
        pdf.set_xy(x_sello + 3, y_start + 14)
        pdf.set_font("helvetica", "", 10)
        pdf.cell(w_sello, 6, txt="Fecha: ........ / ........ / ........", ln=True)
        
        pdf.set_xy(x_sello + 3, y_start + 23)
        pdf.cell(w_sello, 6, txt="Asiento: ...................................", ln=True)
        
        y_final = max(pdf.get_y(), y_start + h_sello)
        pdf.set_y(y_final + 10)
        
    return bytes(pdf.output())


# --- PANEL LATERAL ---
with st.sidebar:
    st.title("📁 Mis Exportaciones")
    st.markdown("---")
    nueva_orden = st.text_input("Número de Exportación")
    if st.button("Crear Exportación", use_container_width=True):
        if nueva_orden and nueva_orden not in st.session_state['exportaciones']:
            st.session_state['exportaciones'][nueva_orden] = {"factura": {}, "swifts": [], "liquidaciones": []}
            st.session_state['orden_actual'] = nueva_orden
            guardar_datos(st.session_state['exportaciones'])
            st.success("Creada.")
            st.rerun()
            
    st.markdown("---")
    st.markdown("**Exportaciones Guardadas:**")
    
    # Renderizar botones con % de conciliación
    for orden, data in st.session_state['exportaciones'].items():
        total_factura = data.get("factura", {}).get("total_usd", 0.0)
        total_cobrado = sum(s.get("usd_swift", 0.0) for s in data.get("swifts", []))
        
        if total_factura > 0:
            pct = (total_cobrado / total_factura) * 100
            if pct >= 99.5:
                icono = "🟢 100%"
            elif pct > 0:
                icono = f"🟡 {int(pct)}%"
            else:
                icono = "🔴 0%"
        else:
            icono = "⚪ S/F" # Sin Factura
            
        if st.button(f"{icono} | {orden}", key=f"btn_{orden}", use_container_width=True):
            st.session_state['orden_actual'] = orden
            st.rerun()

# --- PANEL PRINCIPAL ---
if st.session_state['orden_actual']:
    orden_id = st.session_state['orden_actual']
    exp_data = st.session_state['exportaciones'][orden_id]
    
    col_title, col_btn = st.columns([0.8, 0.2])
    with col_title: st.title(f"Exportación: {orden_id}")
    with col_btn:
        if st.button("🗑️ Limpiar Datos", use_container_width=True):
            st.session_state['exportaciones'][orden_id] = {"factura": {}, "swifts": [], "liquidaciones": []}
            guardar_datos(st.session_state['exportaciones'])
            st.rerun()
            
    st.markdown("Carga los PDFs (Factura, Swifts y Avisos de Crédito) correspondientes.")
    archivos = st.file_uploader("Subir archivos PDF", type="pdf", accept_multiple_files=True, key=f"uploader_{orden_id}")
    
    if st.button("Procesar Archivos", type="primary"):
        for archivo in archivos:
            datos = procesar_pdf(archivo)
            if datos["tipo"] == "Factura":
                exp_data["factura"] = datos
            elif datos["tipo"] == "Swift":
                if "swifts" not in exp_data: exp_data["swifts"] = []
                exp_data["swifts"] = [s for s in exp_data["swifts"] if s.get("usd_swift") != datos.get("usd_swift")]
                exp_data["swifts"].append(datos)
            elif datos["tipo"] == "Liquidacion":
                if "liquidaciones" not in exp_data: exp_data["liquidaciones"] = []
                exp_data["liquidaciones"] = [l for l in exp_data["liquidaciones"] if l.get("usd_liquidado") != datos.get("usd_liquidado")]
                exp_data["liquidaciones"].append(datos)
        
        guardar_datos(st.session_state['exportaciones'])
        st.success("Archivos procesados y guardados en memoria.")
        st.rerun()

    st.divider()

    datos_factura = exp_data.get("factura", {})
    tc_factura = datos_factura.get("tc_factura", 0.0)
    total_usd_factura = datos_factura.get("total_usd", 0.0)
    swifts_guardados = exp_data.get("swifts", [])
    liquidaciones_guardadas = exp_data.get("liquidaciones", [])

    # Datos Factura UI
    if datos_factura:
        st.subheader("🧾 Datos de la Factura")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Fecha:** {datos_factura.get('fecha', 'N/A')}")
        c1.markdown(f"**Número:** {datos_factura.get('nro_factura', 'N/A')}")
        c2.markdown(f"**Cliente:** {datos_factura.get('cliente', 'N/A')}")
        c3.markdown(f"**Monto:** USD ${formato_arg(total_usd_factura)}")
        c3.markdown(f"**Tipo de Cambio:** {formato_arg(tc_factura)}")
        st.divider()

    # Datos Cobros UI
    if tc_factura > 0 and swifts_guardados:
        swifts_ordenados = sorted(swifts_guardados, key=lambda x: 0 if x.get("etiqueta") == "Anticipo" else 1)
        
        for swift in swifts_ordenados:
            etiqueta = swift.get("etiqueta", "Cobro")
            usd_swift = swift.get("usd_swift", 0.0)
            gastos_swift = swift.get("gastos_swift", 0.0)
            liq = next((l for l in liquidaciones_guardadas if abs(l.get("usd_liquidado", 0) - usd_swift) < 1.0), None)
            
            st.subheader(f"📌 {etiqueta}:")
            
            if liq:
                tc_banco = liq.get("tc_banco", 0.0)
                
                # Conversión a pesos
                swift_ars = usd_swift * tc_banco
                gastos_swift_ars = gastos_swift * tc_banco
                comision_ars = liq.get("usd_comision", 0.0) * tc_banco
                rg2408_ars = liq.get("usd_rg2408", 0.0) * tc_banco
                iva_ars = liq.get("usd_iva", 0.0) * tc_banco
                
                brecha = tc_banco - tc_factura
                resultado_ars = usd_swift * brecha
                
                if resultado_ars < 0:
                    txt_res = f"-${formato_arg(abs(resultado_ars))} ARS"
                else:
                    txt_res = f"${formato_arg(resultado_ars)} ARS"

                st.markdown(f"**Swift (Operación):** ${formato_arg(swift_ars)} ARS")
                st.markdown(f"**Gastos de Transacción (Swift):** ${formato_arg(gastos_swift_ars)} ARS")
                st.markdown(f"**Comisión:** ${formato_arg(comision_ars)} ARS")
                st.markdown(f"**RG2408:** ${formato_arg(rg2408_ars)} ARS")
                st.markdown(f"**IVA 21%:** ${formato_arg(iva_ars)} ARS")
                st.markdown(f"**Resultado financiero:** {txt_res}")
            else:
                st.markdown(f"**Swift (Operación):** USD ${formato_arg(usd_swift)}")
                st.markdown(f"**Gastos de Transacción (Swift):** USD ${formato_arg(gastos_swift)}")
                st.warning("*(Falta cargar el Aviso de Crédito correspondiente para pesificar)*")
            st.write("")
            
        # BOTÓN DESCARGA PDF
        st.divider()
        col_pdf, _ = st.columns([0.4, 0.6])
        with col_pdf:
            pdf_bytes = generar_pdf_impresion(orden_id, exp_data)
            st.download_button(
                label="🖨️ Descargar PDF para Imprimir",
                data=pdf_bytes,
                file_name=f"Conciliacion_{orden_id}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
            
    elif not datos_factura:
        st.info("💡 Asegúrate de cargar la Factura de Exportación para visualizar los cálculos.")
else:
    st.info("👈 Crea o selecciona una exportación en el panel lateral.")

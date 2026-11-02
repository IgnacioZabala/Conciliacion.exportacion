import streamlit as st
import pdfplumber
import re
import json
import os
import io
from fpdf import FPDF
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

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

# --- INTEGRACIÓN CON GOOGLE DRIVE ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

@st.cache_resource
def obtener_servicio_drive():
    try:
        credentials = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        st.error(f"Error de autenticación con Drive: Verifica que el archivo credentials.json esté en la carpeta. Detalle: {e}")
        return None

def obtener_archivos_de_carpeta(service, folder_id):
    """Obtiene la lista de archivos PDF dentro de una carpeta específica."""
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def descargar_pdf_en_memoria(service, file_id):
    """Descarga el PDF y lo devuelve como un objeto BytesIO que pdfplumber puede leer."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

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
    pdf.ln(10)

    swifts_guardados = exp_data.get("swifts", [])
    liquidaciones_guardadas = exp_data.get("liquidaciones", [])
    swifts_ordenados = sorted(swifts_guardados, key=lambda x: 0 if x.get("etiqueta") == "Anticipo" else 1)
    total_instruido = 0.0

    for swift in swifts_ordenados:
        etiqueta = swift.get("etiqueta", "Cobro")
        usd_swift = swift.get("usd_swift", 0.0)
        gastos_swift = swift.get("gastos_swift", 0.0)
        total_instruido += (usd_swift + gastos_swift)
        
        liq = next((l for l in liquidaciones_guardadas if abs(l.get("usd_liquidado", 0) - usd_swift) < 1.0), None)
        
        y_start = pdf.get_y()
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(115, 8, txt=f"{etiqueta}:", ln=True)
        pdf.set_font("helvetica", "", 10)
        
        if liq:
            tc_banco = liq.get("tc_banco", 0.0)
            swift_ars = usd_swift * tc_banco
            comision_ars = liq.get("usd_comision", 0.0) * tc_banco
            rg2408_ars = liq.get("usd_rg2408", 0.0) * tc_banco
            iva_ars = liq.get("usd_iva", 0.0) * tc_banco
            
            total_gastos_bancarios = comision_ars + rg2408_ars + iva_ars
            
            brecha = tc_banco - tc_factura
            resultado_ars = usd_swift * brecha
            
            if resultado_ars < 0: txt_res = f"-${formato_arg(abs(resultado_ars))} ARS"
            else: txt_res = f"${formato_arg(resultado_ars)} ARS"

            pdf.cell(115, 6, txt=f"Total operacion: ${formato_arg(swift_ars)} ARS (USD${formato_arg(usd_swift)})", ln=True)
            pdf.cell(115, 6, txt=f"1- Comision: ${formato_arg(comision_ars)} ARS", ln=True)
            pdf.cell(115, 6, txt=f"2- Gastos de Transaccion: ${formato_arg(total_gastos_bancarios)} ARS", ln=True)
            pdf.cell(115, 6, txt=f"   (Comision: ${formato_arg(comision_ars)} | RG2408: ${formato_arg(rg2408_ars)} | IVA: ${formato_arg(iva_ars)})", ln=True)
            pdf.cell(115, 6, txt=f"3- Resultado financiero: {txt_res}", ln=True)
        else:
            pdf.cell(115, 6, txt=f"Total operacion: USD ${formato_arg(usd_swift)}", ln=True)
            pdf.cell(115, 6, txt=f"1- Comision: (Falta Aviso de Credito)", ln=True)
            pdf.cell(115, 6, txt=f"2- Gastos de Transaccion: USD ${formato_arg(gastos_swift)}", ln=True)
            pdf.cell(115, 6, txt="3- Resultado financiero: (Falta Aviso de Credito)", ln=True)

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
        pdf.set_y(y_final + 15)

    if total_factura_usd > 0 and total_instruido > 0:
        pdf.ln(5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(0, 6, txt="Validacion de Cobro Total:", ln=True)
        pdf.set_font("helvetica", "", 10)
        
        for swift in swifts_ordenados:
            s_neto = swift.get("usd_swift", 0.0)
            s_gasto = swift.get("gastos_swift", 0.0)
            pdf.cell(0, 6, txt=f"- {swift.get('etiqueta')}: USD ${formato_arg(s_neto)} (Neto) + USD ${formato_arg(s_gasto)} (Swift) = USD${formato_arg(s_neto + s_gasto)}", ln=True)
            
        pdf.ln(3)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 6, txt=f"Total Pagado por Cliente: USD ${formato_arg(total_instruido)}", ln=True)
        pdf.cell(0, 6, txt=f"Total Facturado: USD ${formato_arg(total_factura_usd)}", ln=True)
        
        if abs(total_factura_usd - total_instruido) < 0.01:
            pdf.cell(0, 8, txt="ESTADO: 100% COBRADO (Los montos coinciden exactamente)", ln=True)
        else:
            pdf.cell(0, 8, txt=f"ESTADO: PENDIENTE (Diferencia de USD ${formato_arg(total_factura_usd - total_instruido)})", ln=True)

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
    
    for orden, data in st.session_state['exportaciones'].items():
        total_factura = data.get("factura", {}).get("total_usd", 0.0)
        total_cobrado = sum(s.get("usd_swift", 0.0) + s.get("gastos_swift", 0.0) for s in data.get("swifts", []))
        
        if total_factura > 0:
            pct = (total_cobrado / total_factura) * 100
            if pct >= 99.5:
                icono = "🟢 100%"
            elif pct > 0:
                icono = f"🟡 {int(pct)}%"
            else:
                icono = "🔴 0%"
        else:
            icono = "⚪ S/F"
            
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
            
    st.markdown("Sincroniza los PDFs directamente desde la carpeta de esta exportación en Google Drive.")
    
    # Campo para ingresar el ID de la carpeta
    carpeta_drive_id = st.text_input("ID de la Carpeta de Google Drive", 
                                     help="Copia el código final de la URL cuando entras a la carpeta en Drive. Ej: 1aB2c3D4e5F6g7H8i9J0")

    if st.button("Sincronizar y Procesar desde Drive", type="primary"):
        if not carpeta_drive_id:
            st.warning("Por favor, ingresa el ID de la carpeta.")
        else:
            service = obtener_servicio_drive()
            if service:
                with st.spinner('Conectando a Google Drive...'):
                    archivos_drive = obtener_archivos_de_carpeta(service, carpeta_drive

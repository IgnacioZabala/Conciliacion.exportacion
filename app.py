import streamlit as st
import pdfplumber
import json
import re
import os
from fpdf import FPDF

# ---------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS TIPO GOOGLE SITES
# ---------------------------------------------------------
st.set_page_config(page_title="Conciliación de Exportación", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    /* Estilo Global Google Sites / Material Modern */
    .stApp {
        background-color: #f8f9fa;
        font-family: 'Google Sans', 'Inter', -apple-system, sans-serif;
    }
    
    /* Panel Lateral Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid #e0e3e7 !important;
    }
    
    /* Botones estilo Google */
    .stButton>button {
        border-radius: 20px !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
    }
    
    /* Tarjetas redondeadas Google Sites */
    .g-card {
        background: #ffffff;
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 20px;
        border: 1px solid #e3e8ef;
        box-shadow: 0 1px 3px rgba(60,64,67,0.08);
    }
    
    /* Estilizado de inputs */
    div[data-baseweb="input"] {
        border-radius: 10px !important;
    }
    </style>
""", unsafe_allow_html=True)

DATA_FILE = "export_operations.json"

# ---------------------------------------------------------
# PERSISTENCIA EN DISCO (JSON)
# ---------------------------------------------------------
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [{
        "id": 1,
        "client": "",
        "factura_nro": "",
        "fecha": "",
        "kilos": 0.0,
        "importe_usd": 0.0,
        "tc_factura": 0.0,
        "anticipo": {"fecha": "", "swift_usd": 0.0, "gasto_swift": 0.0, "tc_liq": 0.0, "comision": 0.0, "rg": 0.0, "iva": 0.0, "acreditado": 0.0},
        "restante": {"fecha": "", "swift_usd": 0.0, "gasto_swift": 0.0, "tc_liq": 0.0, "comision": 0.0, "rg": 0.0, "iva": 0.0, "acreditado": 0.0}
    }]

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.export_operations, f, ensure_ascii=False, indent=2)

if "export_operations" not in st.session_state:
    st.session_state.export_operations = load_data()

if "current_id" not in st.session_state:
    st.session_state.current_id = st.session_state.export_operations[0]["id"]

# ---------------------------------------------------------
# PARSERS DE TEXTO Y NÚMEROS
# ---------------------------------------------------------
def parse_num(val_str):
    if not val_str:
        return 0.0
    cleaned = str(val_str).strip()
    cleaned = re.sub(r'[^0-9\.,]', '', cleaned)
    if not cleaned:
        return 0.0
    if "." in cleaned and "," in cleaned:
        if cleaned.rfind(".") < cleaned.rfind(","):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def extract_factura_e(file):
    res = {}
    with pdfplumber.open(file) as pdf:
        text = " ".join([page.extract_text() or "" for page in pdf.pages])
        clean = re.sub(r'\s+', ' ', text)
        
        nro_match = re.search(r'Compr\.?\s*Nro[:\s]*([0-9]{4,5})\s*-\s*([0-9]{8})', clean, re.I) or re.search(r'([0-9]{4,5}-[0-9]{8})', clean)
        if nro_match:
            res['factura_nro'] = f"{nro_match.group(1)}-{nro_match.group(2)}" if len(nro_match.groups()) > 1 else nro_match.group(1)
            
        fecha_match = re.search(r'([0-9]{2}/[0-9]{2}/[0-9]{4})', clean)
        if fecha_match:
            res['fecha'] = fecha_match.group(1)

        cliente_match = re.search(r'Se[ñn]or[^\:]*:\s*(.*?)(?=\s+(?:CUIT|ID\s+Impositivo|Domicilio|Divisa|Destino|Condici[oó]n))', clean, re.I)
        if cliente_match:
            res['client'] = cliente_match.group(1).strip()

        total_match = re.search(r'(?:Importe\s+Total|Total\s+por\s+item)[^0-9]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})', clean, re.I)
        if total_match:
            res['importe_usd'] = parse_num(total_match.group(1))

        tc_match = re.search(r'Tipo\s+de\s+Cambio[^0-9]*([0-9]+(?:[\.,][0-9]+)?)', clean, re.I)
        if tc_match:
            res['tc_factura'] = parse_num(tc_match.group(1))

        kg_match = re.search(r'([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{6}|[0-9]+,[0-9]{6})', clean)
        if kg_match:
            res['kilos'] = parse_num(kg_match.group(1))
            
    return res

def extract_swift(file):
    res = {}
    with pdfplumber.open(file) as pdf:
        text = " ".join([page.extract_text() or "" for page in pdf.pages])
        clean = re.sub(r'\s+', ' ', text)
        
        m_swift = re.search(r'([0-9\.,]+)\s+Cobro\s+(?:Anticipado|definitivo|saldo|Restante)', clean, re.I) or \
                  re.search(r'Importe\s+instruido[^0-9]*([0-9\.,]+)', clean, re.I) or \
                  re.search(r'Monto\s+operaci[oó]n[^0-9]*([0-9\.,]+)', clean, re.I) or \
                  re.search(r'USD\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})', clean, re.I) or \
                  re.search(r':32B:[A-Z]{3}([0-9\.,]+)', clean, re.I)
        if m_swift:
            res['swift_usd'] = parse_num(m_swift.group(1))

        m_gasto = re.search(r'Gastos\s+de\s+transacci[oó]n[^\d]*([0-9\.,]+)', clean, re.I) or \
                  re.search(r'Gasto\s+swift[^\d]*([0-9\.,]+)', clean, re.I) or \
                  re.search(r'portador\s+de\s+los\s+gastos\s*:\s*([0-9\.,]+)', clean, re.I) or \
                  re.search(r':71F:[A-Z]{3}([0-9\.,]+)', clean, re.I)
        if m_gasto:
            res['gasto_swift'] = parse_num(m_gasto.group(1))
    return res

def extract_aviso(file):
    res = {}
    with pdfplumber.open(file) as pdf:
        text = " ".join([page.extract_text() or "" for page in pdf.pages])
        clean = re.sub(r'\s+', ' ', text)
        
        # Fecha
        f_match = re.search(r'Fecha\s+(?:reporte|operaci[oó]n|liquidaci[oó]n|cierre|acred|emisi[oó]n)?:?\s*([0-9]{2}/[0-9]{2}/[0-9]{2,4})', clean, re.I) or \
                  re.search(r'FECHA:?\s*([0-9]{2}/[0-9]{2}/[0-9]{2,4})', clean, re.I) or \
                  re.search(r'([0-9]{2}/[0-9]{2}/[0-9]{4})', clean)
        if f_match:
            res['fecha'] = f_match.group(1)

        # PARSING MEJORADO DE T.C. LIQUIDACIÓN
        tc_found = False
        tc_patterns = [
            r'(?:TIPO\s+DE?\s+CAMBIO|T\.C\.|COTIZACI[OÓ]N|CAMBIO|T/C)\s*[:\$=]?\s*\b([0-9]{1,2}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]{3,4}(?:,[0-9]{1,4})?)\b',
            r'USD\s*[:\$=]?\s*\b([0-9]{1,2}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]{3,4},[0-9]{2})\b'
        ]
        
        for pat in tc_patterns:
            matches = re.finditer(pat, clean, re.I)
            for mt in matches:
                val = parse_num(mt.group(1))
                if 500 <= val <= 4000:
                    res['tc_liq'] = val
                    tc_found = True
                    break
            if tc_found:
                break

        if not tc_found:
            # Búsqueda estricta de formato ARS para cotizaciones (ej. 1.371,00 o 1438,00)
            all_candidates = re.findall(r'\b([1-9]\.[0-9]{3},[0-9]{2}|[5-9][0-9]{2},[0-9]{2}|1[0-9]{3},[0-9]{2})\b', clean)
            for cand in all_candidates:
                val = parse_num(cand)
                if 500 <= val <= 4000:
                    res['tc_liq'] = val
                    break

        # Importe Acreditado en Pesos
        acred_match = re.search(r'(?:Importe\s+acreditado|Liquidado\s+en\s+Cta|Neto\s+Acreditado|Total\s+Acreditado|ACREDITAR|IMPORTE\s+NETO)[^\d]*\b([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\b', clean, re.I)
        if acred_match:
            res['acreditado'] = parse_num(acred_match.group(1))

        # Comisión / RG 2408 / IVA 21%
        com_match = re.search(r'COMISION[^\$]*?USD\s+[0-9\.,]+\s+[0-9\.,]+\s+([0-9\.,]+)', clean, re.I) or \
                    re.search(r'COMISI[OÓ]N[^\d]*\b([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\b', clean, re.I)
        if com_match:
            res['comision'] = parse_num(com_match.group(1))

        rg_match = re.search(r'RG2408[^\$]*?USD\s+[0-9\.,]+\s+[0-9\.,]+\s+([0-9\.,]+)', clean, re.I) or \
                   re.search(r'RG\s*2408[^\d]*\b([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\b', clean, re.I)
        if rg_match:
            res['rg'] = parse_num(rg_match.group(1))

        iva_match = re.search(r'IVA\s+21%[^\$]*?USD\s+[0-9\.,]+\s+[0-9\.,]+\s+([0-9\.,]+)', clean, re.I) or \
                    re.search(r'IVA\s+21%[^\d]*\b([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\b', clean, re.I)
        if iva_match:
            res['iva'] = parse_num(iva_match.group(1))

    return res

# ---------------------------------------------------------
# CALLBACKS DE CARGA DE ARCHIVOS
# ---------------------------------------------------------
def process_pdf_factura(key_name, op_id):
    file = st.session_state.get(f"uploader_fac_{key_name}_{op_id}")
    if file:
        data = extract_factura_e(file)
        op = next((o for o in st.session_state.export_operations if o["id"] == op_id), None)
        if op:
            op.update(data)
            if "client" in data: st.session_state[f"main_client_{op_id}"] = data["client"]
            if "factura_nro" in data: st.session_state[f"main_fnro_{op_id}"] = data["factura_nro"]
            if "fecha" in data: st.session_state[f"main_fecha_{op_id}"] = data["fecha"]
            if "kilos" in data: st.session_state[f"main_kg_{op_id}"] = float(data["kilos"])
            if "importe_usd" in data: st.session_state[f"main_imp_{op_id}"] = float(data["importe_usd"])
            if "tc_factura" in data: st.session_state[f"main_tc_{op_id}"] = float(data["tc_factura"])
            save_data()

def process_pdf_swift(key_name, op_id):
    file = st.session_state.get(f"uploader_swift_{key_name}_{op_id}")
    if file:
        data = extract_swift(file)
        op = next((o for o in st.session_state.export_operations if o["id"] == op_id), None)
        if op:
            op[key_name].update(data)
            if "swift_usd" in data: st.session_state[f"sw_{key_name}_{op_id}"] = float(data["swift_usd"])
            if "gasto_swift" in data: st.session_state[f"gw_{key_name}_{op_id}"] = float(data["gasto_swift"])
            
            sub = op[key_name]
            if sub["tc_liq"] > 0:
                acred_calc = max(0.0, (sub["swift_usd"] - sub["gasto_swift"]) * sub["tc_liq"] - sub["comision"] - sub["rg"] - sub["iva"])
                sub["acreditado"] = acred_calc
                st.session_state[f"ac_{key_name}_{op_id}"] = float(acred_calc)
            save_data()

def process_pdf_aviso(key_name, op_id):
    file = st.session_state.get(f"uploader_aviso_{key_name}_{op_id}")
    if file:
        data = extract_aviso(file)
        op = next((o for o in st.session_state.export_operations if o["id"] == op_id), None)
        if op:
            op[key_name].update(data)
            sub = op[key_name]
            if "fecha" in data: st.session_state[f"f_{key_name}_{op_id}"] = data["fecha"]
            if "tc_liq" in data: st.session_state[f"tc_{key_name}_{op_id}"] = float(data["tc_liq"])
            if "comision" in data: st.session_state[f"cm_{key_name}_{op_id}"] = float(data["comision"])
            if "rg" in data: st.session_state[f"rg_{key_name}_{op_id}"] = float(data["rg"])
            if "iva" in data: st.session_state[f"iva_{key_name}_{op_id}"] = float(data["iva"])
            
            if data.get("acreditado", 0) > 0:
                st.session_state[f"ac_{key_name}_{op_id}"] = float(data["acreditado"])
            elif sub["tc_liq"] > 0 and sub["swift_usd"] > 0:
                acred_calc = max(0.0, (sub["swift_usd"] - sub["gasto_swift"]) * sub["tc_liq"] - sub["comision"] - sub["rg"] - sub["iva"])
                sub["acreditado"] = acred_calc
                st.session_state[f"ac_{key_name}_{op_id}"] = float(acred_calc)
            save_data()

# ---------------------------------------------------------
# GENERADOR DE REPORTES PDF
# ---------------------------------------------------------
def generate_pdf_report(op):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Conciliacion de Exportacion - Factura {op.get('factura_nro', 'S/N')}", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Cliente: {op.get('client', 'N/A')}", ln=True)
    pdf.cell(0, 8, f"Fecha: {op.get('fecha', 'N/A')} | Importe: USD {op.get('importe_usd', 0):,.2f} | T.C. Factura: ${op.get('tc_factura', 0):,.2f}", ln=True)
    pdf.ln(5)

    for parte_name, key in [("ANTICIPIOS", "anticipo"), ("RESTANTE / SALDO", "restante")]:
        p = op[key]
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, parte_name, ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"  Swift: USD {p['swift_usd']:,.2f} | Gasto Swift: USD {p['gasto_swift']:,.2f}", ln=True)
        pdf.cell(0, 6, f"  T.C. Liquidação: ${p['tc_liq']:,.2f} | Acreditado: ${p['acreditado']:,.2f}", ln=True)
        pdf.cell(0, 6, f"  Comision: ${p['comision']:,.2f} | RG 2408: ${p['rg']:,.2f} | IVA: ${p['iva']:,.2f}", ln=True)
        pdf.ln(3)

    return bytes(pdf.output())

# ---------------------------------------------------------
# SINCRONIZACIÓN INICIAL Y OPERACIÓN ACTIVA
# ---------------------------------------------------------
current_op = next((op for op in st.session_state.export_operations if op["id"] == st.session_state.current_id), None)
if not current_op:
    current_op = st.session_state.export_operations[0]
    st.session_state.current_id = current_op["id"]

op_id = current_op["id"]

def sync_op_to_state(op):
    oid = op["id"]
    if f"main_client_{oid}" not in st.session_state:
        st.session_state[f"main_client_{oid}"] = op["client"]
        st.session_state[f"main_fnro_{oid}"] = op["factura_nro"]
        st.session_state[f"main_fecha_{oid}"] = op["fecha"]
        st.session_state[f"main_kg_{oid}"] = float(op["kilos"])
        st.session_state[f"main_imp_{oid}"] = float(op["importe_usd"])
        st.session_state[f"main_tc_{oid}"] = float(op["tc_factura"])

        for key_name in ["anticipo", "restante"]:
            sub = op[key_name]
            st.session_state[f"f_{key_name}_{oid}"] = sub["fecha"]
            st.session_state[f"sw_{key_name}_{oid}"] = float(sub["swift_usd"])
            st.session_state[f"gw_{key_name}_{oid}"] = float(sub["gasto_swift"])
            st.session_state[f"tc_{key_name}_{oid}"] = float(sub["tc_liq"])
            st.session_state[f"cm_{key_name}_{oid}"] = float(sub["comision"])
            st.session_state[f"rg_{key_name}_{oid}"] = float(sub["rg"])
            st.session_state[f"iva_{key_name}_{oid}"] = float(sub["iva"])
            st.session_state[f"ac_{key_name}_{oid}"] = float(sub["acreditado"])

sync_op_to_state(current_op)

# ---------------------------------------------------------
# PANEL LATERAL CON PORCENTAJE DE COBRO DENTRO DE LA LISTA
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("<h2 style='font-size: 20px; font-weight: 700; color: #1f2937;'>Exportaciones</h2>", unsafe_allow_html=True)
    st.caption(f"{len(st.session_state.export_operations)} activas")
    st.divider()

    for op in st.session_state.export_operations:
        is_selected = op["id"] == st.session_state.current_id
        
        # Cálculo dinámico del % de pago cobrado
        tot_sw = op["anticipo"]["swift_usd"] + op["restante"]["swift_usd"]
        pct = (tot_sw / op["importe_usd"] * 100) if op["importe_usd"] > 0 else 0.0
        
        client_name = op['client'] or 'Sin cliente'
        fnro = op['factura_nro'] or 'S/N'
        
        btn_label = f"{client_name}\n({fnro}) — {pct:.1f}%"
        
        if st.button(btn_label, key=f"btn_op_{op['id']}", type="primary" if is_selected else "secondary", use_container_width=True):
            st.session_state.current_id = op["id"]
            st.rerun()

    st.divider()
    if st.button("+ Nueva Exportación", use_container_width=True):
        new_id = max([o["id"] for o in st.session_state.export_operations], default=0) + 1
        new_op = {
            "id": new_id, "client": "", "factura_nro": "", "fecha": "", "kilos": 0.0, "importe_usd": 0.0, "tc_factura": 0.0,
            "anticipo": {"fecha": "", "swift_usd": 0.0, "gasto_swift": 0.0, "tc_liq": 0.0, "comision": 0.0, "rg": 0.0, "iva": 0.0, "acreditado": 0.0},
            "restante": {"fecha": "", "swift_usd": 0.0, "gasto_swift": 0.0, "tc_liq": 0.0, "comision": 0.0, "rg": 0.0, "iva": 0.0, "acreditado": 0.0}
        }
        st.session_state.export_operations.append(new_op)
        st.session_state.current_id = new_id
        sync_op_to_state(new_op)
        save_data()
        st.rerun()

# ---------------------------------------------------------
# CONTENIDO PRINCIPAL EN TARJETAS ESTILO GOOGLE SITES
# ---------------------------------------------------------
col_t1, col_t2 = st.columns([3, 1])
with col_t1:
    st.markdown(f"<h1 style='font-size: 28px; font-weight: 700; color: #1a73e8; margin-bottom: 0;'>Conciliación de Exportación</h1>", unsafe_allow_html=True)
    st.caption(f"Factura: {st.session_state[f'main_fnro_{op_id}'] or 'S/N'} — Cliente: {st.session_state[f'main_client_{op_id}'] or 'Sin cliente'}")

with col_t2:
    if st.button("💾 Guardar Cambios", use_container_width=True, type="primary"):
        save_data()
        st.toast("¡Datos guardados con éxito!", icon="✅")

st.markdown("<br>", unsafe_allow_html=True)

# TARJETA 1: FACTURA E
st.markdown("<div class='g-card'>", unsafe_allow_html=True)
st.markdown("<h3 style='font-size: 16px; font-weight: 700; color: #3c4043; margin-bottom: 16px;'>Factura E</h3>", unsafe_allow_html=True)
c1, c2, c3, c4, c5, c6 = st.columns(6)

current_op["client"] = c1.text_input("Cliente", key=f"main_client_{op_id}")
current_op["factura_nro"] = c2.text_input("N° Factura E", key=f"main_fnro_{op_id}")
current_op["fecha"] = c3.text_input("Fecha", key=f"main_fecha_{op_id}")
current_op["kilos"] = c4.number_input("Kg Producto", format="%.2f", key=f"main_kg_{op_id}")
current_op["importe_usd"] = c5.number_input("Importe USD", format="%.2f", key=f"main_imp_{op_id}")
current_op["tc_factura"] = c6.number_input("T.C. Factura", format="%.2f", key=f"main_tc_{op_id}")
st.markdown("</div>", unsafe_allow_html=True)

# SECCIONES ANTICIPO Y RESTANTE
def render_section(title, key_name):
    st.markdown("<div class='g-card'>", unsafe_allow_html=True)
    sub_data = current_op[key_name]
    
    st.markdown(f"<h3 style='font-size: 16px; font-weight: 700; color: #3c4043; margin-bottom: 16px;'>{title}</h3>", unsafe_allow_html=True)
    
    # Carga de PDFs
    f1, f2, f3 = st.columns(3)
    f1.file_uploader(f"Factura E ({title})", type=["pdf"], key=f"uploader_fac_{key_name}_{op_id}", on_change=process_pdf_factura, args=(key_name, op_id))
    f2.file_uploader(f"SWIFT ({title})", type=["pdf"], key=f"uploader_swift_{key_name}_{op_id}", on_change=process_pdf_swift, args=(key_name, op_id))
    f3.file_uploader(f"Aviso Crédito ({title})", type=["pdf"], key=f"uploader_aviso_{key_name}_{op_id}", on_change=process_pdf_aviso, args=(key_name, op_id))

    # Inputs Editables
    col_a, col_b, col_c, col_d, col_e, col_f, col_g, col_h = st.columns(8)
    sub_data["fecha"] = col_a.text_input("Fecha Acred.", key=f"f_{key_name}_{op_id}")
    sub_data["swift_usd"] = col_b.number_input("Swift USD", format="%.2f", key=f"sw_{key_name}_{op_id}")
    sub_data["gasto_swift"] = col_c.number_input("Gasto Swift USD", format="%.2f", key=f"gw_{key_name}_{op_id}")
    sub_data["tc_liq"] = col_d.number_input("T.C. Liq.", format="%.2f", key=f"tc_{key_name}_{op_id}")
    sub_data["comision"] = col_e.number_input("Comisión $", format="%.2f", key=f"cm_{key_name}_{op_id}")
    sub_data["rg"] = col_f.number_input("RG 2408 $", format="%.2f", key=f"rg_{key_name}_{op_id}")
    sub_data["iva"] = col_g.number_input("IVA 21% $", format="%.2f", key=f"iva_{key_name}_{op_id}")
    
    # Autocálculo de acreditado en UI
    if sub_data["acreditado"] == 0 and sub_data["tc_liq"] > 0 and sub_data["swift_usd"] > 0:
        sub_data["acreditado"] = max(0.0, (sub_data["swift_usd"] - sub_data["gasto_swift"]) * sub_data["tc_liq"] - sub_data["comision"] - sub_data["rg"] - sub_data["iva"])
        st.session_state[f"ac_{key_name}_{op_id}"] = float(sub_data["acreditado"])
        
    sub_data["acreditado"] = col_h.number_input("Acreditado $", format="%.2f", key=f"ac_{key_name}_{op_id}")
    st.markdown("</div>", unsafe_allow_html=True)

render_section("Anticipo", "anticipo")
render_section("Restante", "restante")

save_data()

# MÉTRICAS Y RESULTADOS FINANCIEROS
ant = current_op["anticipo"]
res = current_op["restante"]

neto_usd_ant = ant["swift_usd"] - ant["gasto_swift"]
neto_usd_res = res["swift_usd"] - res["gasto_swift"]

result_fin_ant = neto_usd_ant * (ant["tc_liq"] - current_op["tc_factura"]) if current_op["tc_factura"] > 0 else 0.0
result_fin_res = neto_usd_res * (res["tc_liq"] - current_op["tc_factura"]) if current_op["tc_factura"] > 0 else 0.0
total_result_fin = result_fin_ant + result_fin_res

st.markdown("<div class='g-card'>", unsafe_allow_html=True)
st.markdown("<h3 style='font-size: 16px; font-weight: 700; color: #3c4043; margin-bottom: 16px;'>Resumen Financiero</h3>", unsafe_allow_html=True)

m1, m2, m3, m4 = st.columns(4)
total_swift = ant["swift_usd"] + res["swift_usd"]
pct_cobrado = (total_swift / current_op["importe_usd"] * 100) if current_op["importe_usd"] > 0 else 0.0

m1.metric("% Cobrado", f"{pct_cobrado:.2f}%")
m2.metric("Saldo Pendiente USD", f"US$ {max(0.0, current_op['importe_usd'] - total_swift):,.2f}")
m3.metric("Resultado Financiero", f"$ {total_result_fin:,.2f}", delta=f"{total_result_fin:,.2f}")
m4.metric("Total Acreditado $", f"$ {(ant['acreditado'] + res['acreditado']):,.2f}")
st.markdown("</div>", unsafe_allow_html=True)

# EXPORTACIÓN EN PDF
pdf_bytes = generate_pdf_report(current_op)
st.download_button(
    label="📥 Exportar Informe en PDF",
    data=pdf_bytes,
    file_name=f"Conciliacion_{current_op['factura_nro'] or 'SN'}.pdf",
    mime="application/pdf"
)

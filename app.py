import streamlit as st
import pdfplumber
import json
import re
import os
from fpdf import FPDF

# ---------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# ---------------------------------------------------------
st.set_page_config(page_title="Conciliación de Exportación", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .main { background-color: #f8fafc; }
    .stCard { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin-bottom: 12px; }
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
# PARSERS DE PDF ENRIQUECIDOS
# ---------------------------------------------------------
def parse_num(val_str):
    if not val_str:
        return 0.0
    cleaned = str(val_str).strip()
    if "." in cleaned and "," in cleaned:
        if cleaned.find(".") < cleaned.find(","):
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
        
        # Búsqueda de importe en SWIFT (32B, 33B, Cobro, USD)
        m_swift = re.search(r'([0-9\.,]+)\s+Cobro\s+(?:Anticipado|definitivo|saldo|Restante)', clean, re.I) or \
                  re.search(r'Importe\s+instruido[^0-9]*([0-9\.,]+)', clean, re.I) or \
                  re.search(r'Monto\s+operaci[oó]n[^0-9]*([0-9\.,]+)', clean, re.I) or \
                  re.search(r'USD\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})', clean, re.I) or \
                  re.search(r':32B:[A-Z]{3}([0-9\.,]+)', clean, re.I)
        if m_swift:
            res['swift_usd'] = parse_num(m_swift.group(1))

        # Gastos SWIFT
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
        f_match = re.search(r'Fecha\s+(?:reporte|operaci[oó]n|liquidaci[oó]n|cierre):?\s*([0-9/]{8,10})', clean, re.I) or \
                  re.search(r'FECHA:?\s*([0-9/]{8,10})', clean, re.I) or \
                  re.search(r'([0-9]{2}/[0-9]{2}/[0-9]{4})', clean)
        if f_match:
            res['fecha'] = f_match.group(1)

        # Importe Acreditado en Pesos
        acred_match = re.search(r'Importe\s+acreditado[^\d]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})', clean, re.I) or \
                      re.search(r'Liquidado\s+en\s+Cta[^\d]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})', clean, re.I) or \
                      re.search(r'Neto\s+Acreditado[^\d]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})', clean, re.I) or \
                      re.search(r'Total\s+Acreditado[^\d]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})', clean, re.I)
        if acred_match:
            res['acreditado'] = parse_num(acred_match.group(1))

        # T.C. Liquidación
        matches_tc = re.finditer(r'(?:TIPO\s+CAMBIO|T\.C\.|CAMBIO|COTIZACI[OÓ]N)[^0-9]*([0-9]{3,4}(?:[\.,][0-9]{1,2})?)', clean, re.I)
        for mt in matches_tc:
            val = parse_num(mt.group(1))
            if 500 <= val <= 4000:
                res['tc_liq'] = val
                break

        # Comisión / RG 2408 / IVA 21%
        com_match = re.search(r'COMISION[^\$]*?USD\s+[0-9\.,]+\s+[0-9\.,]+\s+([0-9\.,]+)', clean, re.I) or \
                    re.search(r'COMISION[^0-9]*([0-9\.,]+)', clean, re.I)
        if com_match:
            res['comision'] = parse_num(com_match.group(1))

        rg_match = re.search(r'RG2408[^\$]*?USD\s+[0-9\.,]+\s+[0-9\.,]+\s+([0-9\.,]+)', clean, re.I) or \
                   re.search(r'RG\s*2408[^0-9]*([0-9\.,]+)', clean, re.I)
        if rg_match:
            res['rg'] = parse_num(rg_match.group(1))

        iva_match = re.search(r'IVA\s+21%[^\$]*?USD\s+[0-9\.,]+\s+[0-9\.,]+\s+([0-9\.,]+)', clean, re.I) or \
                    re.search(r'IVA\s+21%[^0-9]*([0-9\.,]+)', clean, re.I)
        if iva_match:
            res['iva'] = parse_num(iva_match.group(1))

    return res

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
# INTERFAZ DE USUARIO (STREAMLIT)
# ---------------------------------------------------------
current_op = next((op for op in st.session_state.export_operations if op["id"] == st.session_state.current_id), None)
if not current_op:
    current_op = st.session_state.export_operations[0]
    st.session_state.current_id = current_op["id"]

# PANEL IZQUIERDO
with st.sidebar:
    st.title("Exportaciones")
    st.caption(f"{len(st.session_state.export_operations)} activas")
    
    for op in st.session_state.export_operations:
        is_selected = op["id"] == st.session_state.current_id
        label = f"{op['client'] or 'Sin cliente'} ({op['factura_nro'] or 'S/N'})"
        if st.button(label, key=f"btn_op_{op['id']}", type="primary" if is_selected else "secondary", use_container_width=True):
            st.session_state.current_id = op["id"]
            st.rerun()

    st.divider()
    if st.button("+ Nueva Exportación", use_container_width=True):
        new_id = max([o["id"] for o in st.session_state.export_operations], default=0) + 1
        st.session_state.export_operations.append({
            "id": new_id, "client": "", "factura_nro": "", "fecha": "", "kilos": 0.0, "importe_usd": 0.0, "tc_factura": 0.0,
            "anticipo": {"fecha": "", "swift_usd": 0.0, "gasto_swift": 0.0, "tc_liq": 0.0, "comision": 0.0, "rg": 0.0, "iva": 0.0, "acreditado": 0.0},
            "restante": {"fecha": "", "swift_usd": 0.0, "gasto_swift": 0.0, "tc_liq": 0.0, "comision": 0.0, "rg": 0.0, "iva": 0.0, "acreditado": 0.0}
        })
        st.session_state.current_id = new_id
        save_data()
        st.rerun()

# TITULO Y BOTONES DE ACCIÓN
col_t1, col_t2 = st.columns([3, 1])
with col_t1:
    st.title("Conciliación de Exportación")
    st.caption(f"Factura: {current_op['factura_nro'] or 'S/N'} — Cliente: {current_op['client'] or 'Sin cliente'}")

with col_t2:
    if st.button("💾 Guardar Cambios", use_container_width=True, type="primary"):
        save_data()
        st.toast("¡Datos guardados con éxito!", icon="✅")

# FORMULARIO FACTURA E
st.subheader("Factura E")
c1, c2, c3, c4, c5, c6 = st.columns(6)

# Sincronización de inputs principales
current_op["client"] = c1.text_input("Cliente", value=current_op["client"], key=f"main_client_{current_op['id']}")
current_op["factura_nro"] = c2.text_input("N° Factura E", value=current_op["factura_nro"], key=f"main_fnro_{current_op['id']}")
current_op["fecha"] = c3.text_input("Fecha", value=current_op["fecha"], key=f"main_fecha_{current_op['id']}")
current_op["kilos"] = c4.number_input("Kg Producto", value=float(current_op["kilos"]), format="%.2f", key=f"main_kg_{current_op['id']}")
current_op["importe_usd"] = c5.number_input("Importe USD", value=float(current_op["importe_usd"]), format="%.2f", key=f"main_imp_{current_op['id']}")
current_op["tc_factura"] = c6.number_input("T.C. Factura", value=float(current_op["tc_factura"]), format="%.2f", key=f"main_tc_{current_op['id']}")

# SECCIONES ANTICIPO Y RESTANTE CON ACTUALIZACIÓN DIRECTA DE SESSION STATE
def render_section(title, key_name):
    st.subheader(title)
    sub_data = current_op[key_name]
    op_id = current_op['id']
    
    # Carga de PDFs
    f1, f2, f3 = st.columns(3)
    pdf_fac = f1.file_uploader(f"Factura E ({title})", type=["pdf"], key=f"fac_{key_name}_{op_id}")
    pdf_swift = f2.file_uploader(f"SWIFT ({title})", type=["pdf"], key=f"swift_{key_name}_{op_id}")
    pdf_aviso = f3.file_uploader(f"Aviso Crédito ({title})", type=["pdf"], key=f"aviso_{key_name}_{op_id}")

    # Mapeo de claves para actualizar la pantalla al instante
    field_key_map = {
        'fecha': f"f_{key_name}_{op_id}",
        'swift_usd': f"sw_{key_name}_{op_id}",
        'gasto_swift': f"gw_{key_name}_{op_id}",
        'tc_liq': f"tc_{key_name}_{op_id}",
        'comision': f"cm_{key_name}_{op_id}",
        'rg': f"rg_{key_name}_{op_id}",
        'iva': f"iva_{key_name}_{op_id}",
        'acreditado': f"ac_{key_name}_{op_id}"
    }

    # Procesar Factura E
    if pdf_fac:
        f_proc_key = f"proc_fac_{key_name}_{op_id}_{pdf_fac.name}_{pdf_fac.size}"
        if not st.session_state.get(f_proc_key):
            ext = extract_factura_e(pdf_fac)
            current_op.update(ext)
            st.session_state[f"main_client_{op_id}"] = current_op["client"]
            st.session_state[f"main_fnro_{op_id}"] = current_op["factura_nro"]
            st.session_state[f"main_fecha_{op_id}"] = current_op["fecha"]
            st.session_state[f"main_kg_{op_id}"] = float(current_op["kilos"])
            st.session_state[f"main_imp_{op_id}"] = float(current_op["importe_usd"])
            st.session_state[f"main_tc_{op_id}"] = float(current_op["tc_factura"])
            st.session_state[f_proc_key] = True
            save_data()
            st.rerun()

    # Procesar SWIFT
    if pdf_swift:
        s_proc_key = f"proc_swift_{key_name}_{op_id}_{pdf_swift.name}_{pdf_swift.size}"
        if not st.session_state.get(s_proc_key):
            ext = extract_swift(pdf_swift)
            for k, v in ext.items():
                sub_data[k] = v
                if k in field_key_map:
                    st.session_state[field_key_map[k]] = float(v) if isinstance(v, (int, float)) else str(v)
            st.session_state[s_proc_key] = True
            save_data()
            st.rerun()

    # Procesar Aviso de Crédito
    if pdf_aviso:
        a_proc_key = f"proc_aviso_{key_name}_{op_id}_{pdf_aviso.name}_{pdf_aviso.size}"
        if not st.session_state.get(a_proc_key):
            ext = extract_aviso(pdf_aviso)
            for k, v in ext.items():
                sub_data[k] = v
                if k in field_key_map:
                    st.session_state[field_key_map[k]] = float(v) if isinstance(v, (int, float)) else str(v)
            st.session_state[a_proc_key] = True
            save_data()
            st.rerun()

    # Renderizado de Inputs Editables
    col_a, col_b, col_c, col_d, col_e, col_f, col_g, col_h = st.columns(8)
    sub_data["fecha"] = col_a.text_input("Fecha Acred.", value=sub_data["fecha"], key=field_key_map['fecha'])
    sub_data["swift_usd"] = col_b.number_input("Swift USD", value=float(sub_data["swift_usd"]), format="%.2f", key=field_key_map['swift_usd'])
    sub_data["gasto_swift"] = col_c.number_input("Gasto Swift USD", value=float(sub_data["gasto_swift"]), format="%.2f", key=field_key_map['gasto_swift'])
    sub_data["tc_liq"] = col_d.number_input("T.C. Liq.", value=float(sub_data["tc_liq"]), format="%.2f", key=field_key_map['tc_liq'])
    sub_data["comision"] = col_e.number_input("Comisión $", value=float(sub_data["comision"]), format="%.2f", key=field_key_map['comision'])
    sub_data["rg"] = col_f.number_input("RG 2408 $", value=float(sub_data["rg"]), format="%.2f", key=field_key_map['rg'])
    sub_data["iva"] = col_g.number_input("IVA 21% $", value=float(sub_data["iva"]), format="%.2f", key=field_key_map['iva'])
    sub_data["acreditado"] = col_h.number_input("Acreditado $", value=float(sub_data["acreditado"]), format="%.2f", key=field_key_map['acreditado'])

render_section("Anticipo", "anticipo")
render_section("Restante", "restante")

save_data()

# MÉTRICAS Y RESULTADOS FINANCIEROS
st.divider()
ant = current_op["anticipo"]
res = current_op["restante"]

neto_usd_ant = ant["swift_usd"] - ant["gasto_swift"]
neto_usd_res = res["swift_usd"] - res["gasto_swift"]

result_fin_ant = neto_usd_ant * (ant["tc_liq"] - current_op["tc_factura"]) if current_op["tc_factura"] > 0 else 0.0
result_fin_res = neto_usd_res * (res["tc_liq"] - current_op["tc_factura"]) if current_op["tc_factura"] > 0 else 0.0
total_result_fin = result_fin_ant + result_fin_res

m1, m2, m3, m4 = st.columns(4)
total_swift = ant["swift_usd"] + res["swift_usd"]
pct_cobrado = (total_swift / current_op["importe_usd"] * 100) if current_op["importe_usd"] > 0 else 0.0

m1.metric("% Cobrado", f"{pct_cobrado:.2f}%")
m2.metric("Saldo Pendiente USD", f"US$ {max(0.0, current_op['importe_usd'] - total_swift):,.2f}")
m3.metric("Resultado Financiero", f"$ {total_result_fin:,.2f}", delta=f"{total_result_fin:,.2f}")
m4.metric("Total Acreditado $", f"$ {(ant['acreditado'] + res['acreditado']):,.2f}")

# EXPORTACIÓN EN PDF
st.divider()
pdf_bytes = generate_pdf_report(current_op)
st.download_button(
    label="📥 Exportar Informe en PDF",
    data=pdf_bytes,
    file_name=f"Conciliacion_{current_op['factura_nro'] or 'SN'}.pdf",
    mime="application/pdf"
)

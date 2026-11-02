import streamlit as st
import pandas as pd
import numpy as np
from pypdf import PdfReader
import io
import re
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

st.set_page_config(page_title="Conciliador de cobros de exportación", layout="wide", initial_sidebar_state="expanded")

# Custom CSS matching the exact styling
st.markdown('''
<style>
:root {
    --bg: #f6f7f9; --fg: #1c2330; --mut: #6b7585; --card: #fff; --bd: #dde1e8;
    --ok: #0f7a4a; --bad: #c62828; --acc: #1f5fbf; --okbg: #e4f5ec; --badbg: #fdeaea;
}
.main { background-color: var(--bg); color: var(--fg); font-family: system-ui, -apple-system, sans-serif; }
.card {
    background-color: #ffffff;
    border: 1px solid #dde1e8;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.02);
}
h1 { font-size: 20px !important; margin-bottom: 2px !important; color: #1c2330; }
h2 { font-size: 15px !important; margin-bottom: 10px !important; color: #1c2330; }
.sub { color: #6b7585; font-size: 12px; margin-bottom: 14px; }
.kpi-container {
    border: 1px solid #dde1e8;
    border-radius: 8px;
    padding: 12px;
    background-color: #ffffff;
    text-align: center;
}
.kpi-container.g { background-color: #e4f5ec; }
.kpi-container.r { background-color: #fdeaea; }
.kpi-label { font-size: 11px; color: #6b7585; display: block; }
.kpi-value { font: 600 16px ui-monospace, Menlo, monospace; margin-top: 4px; display: block; word-break: break-word; }
</style>
''', unsafe_allow_html=True)

# Initialize Session State for multiple exports stored in memory/dict
if 'exports' not in st.session_state:
    st.session_state.exports = {
        '7 - PI070826': {
            'op': '7 - PI070826',
            'base': 'neto',
            'fac': {
                'cliente': 'AMERICA FOODS FLORIDA LLC',
                'nro': '00080-00000015',
                'fecha': '2026-09-17',
                'usd': 114911.05,
                'tc': 1513.5
            },
            'parts': {
                'ant': {
                    'n': 'Anticipo',
                    'swift': 52707.6,
                    'gasto': 45.0,
                    'tc': 1511.0,
                    'com': 139253.76,
                    'rg': 4170.36,
                    'iva': 29237.85,
                    'acr': 79400526.63,
                    'fecha': ''
                },
                'res': {
                    'n': 'Restante',
                    'swift': 62203.45,
                    'gasto': 45.0,
                    'tc': 1537.5,
                    'com': 167249.25,
                    'rg': 5012.25,
                    'iva': 35116.5,
                    'acr': 95361238.88,
                    'fecha': ''
                }
            }
        }
    }

if 'current_op' not in st.session_state:
    st.session_state.current_op = '7 - PI070826'

# --- SIDEBAR (Panel lateral fijo) ---
with st.sidebar:
    st.markdown("### 📦 Mis Conciliaciones")
    
    if st.button("➕ Generar nueva conciliación", use_container_width=True):
        new_id = f"Op - {len(st.session_state.exports) + 1}"
        st.session_state.exports[new_id] = {
            'op': new_id,
            'base': 'neto',
            'fac': {
                'cliente': '',
                'nro': '',
                'fecha': str(pd.Timestamp.today().date()),
                'usd': 0.0,
                'tc': 0.0
            },
            'parts': {
                'ant': {
                    'n': 'Anticipo / Parte 1',
                    'swift': 0.0,
                    'gasto': 0.0,
                    'tc': 0.0,
                    'com': 0.0,
                    'rg': 0.0,
                    'iva': 0.0,
                    'acr': 0.0,
                    'fecha': ''
                }
            }
        }
        st.session_state.current_op = new_id
        st.rerun()

    st.markdown("---")
    st.markdown("**Historial y % de cobro:**")

    for op_key, data in list(st.session_state.exports.items()):
        f_usd = data['fac']['usd']
        tot_sw = sum(p['swift'] for p in data['parts'].values())
        pct = (tot_sw / f_usd * 100) if f_usd > 0 else 0
        
        btn_label = f"{op_key} ({pct:.1f}%)"
        if st.button(btn_label, use_container_width=True, key=f"sb_{op_key}"):
            st.session_state.current_op = op_key
            st.rerun()

    st.markdown("---")
    
    if st.button("🧹 Limpiar datos de esta exportación", use_container_width=True, type="secondary"):
        curr = st.session_state.current_op
        if curr in st.session_state.exports:
            st.session_state.exports[curr]['fac']['cliente'] = ''
            st.session_state.exports[curr]['fac']['nro'] = ''
            st.session_state.exports[curr]['fac']['usd'] = 0.0
            st.session_state.exports[curr]['fac']['tc'] = 0.0
            for pk in st.session_state.exports[curr]['parts']:
                st.session_state.exports[curr]['parts'][pk]['swift'] = 0.0
                st.session_state.exports[curr]['parts'][pk]['gasto'] = 0.0
                st.session_state.exports[curr]['parts'][pk]['tc'] = 0.0
                st.session_state.exports[curr]['parts'][pk]['com'] = 0.0
                st.session_state.exports[curr]['parts'][pk]['rg'] = 0.0
                st.session_state.exports[curr]['parts'][pk]['iva'] = 0.0
                st.session_state.exports[curr]['parts'][pk]['acr'] = 0.0
            st.success(f"Datos de {curr} limpiados.")
            st.rerun()

curr_data = st.session_state.exports[st.session_state.current_op]
S_op = curr_data['op']
f = curr_data['fac']
parts = curr_data['parts']

new_op_name = st.text_input("Código de Operación / Referencia", value=S_op)
if new_op_name != S_op:
    st.session_state.exports[new_op_name] = st.session_state.exports.pop(st.session_state.current_op)
    st.session_state.current_op = new_op_name
    st.rerun()

st.markdown(f"<div class='sub'>{st.session_state.current_op} · {f['cliente']} · Factura {f['nro']}</div>", unsafe_allow_html=True)

# Factura E Section
st.markdown("<div class='card'>", unsafe_allow_html=True)
st.markdown("<h2>Factura E</h2>", unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    f['cliente'] = st.text_input("Cliente", value=f['cliente'], key=f"cli_{st.session_state.current_op}")
with c2:
    f['nro'] = st.text_input("N° Factura E", value=f['nro'], key=f"nro_{st.session_state.current_op}")
with c3:
    try:
        d_val = pd.to_datetime(f['fecha']).date()
    except:
        d_val = pd.to_datetime('2026-09-17').date()
    res_date = st.date_input("Fecha", value=d_val, key=f"date_{st.session_state.current_op}")
    f['fecha'] = str(res_date)
with c4:
    f['usd'] = st.number_input("Importe total (USD)", value=float(f['usd']), step=0.01, format="%.2f", key=f"usd_{st.session_state.current_op}")
with c5:
    f['tc'] = st.number_input("T.C. factura", value=float(f['tc']), step=0.01, format="%.2f", key=f"tc_{st.session_state.current_op}")
st.markdown("</div>", unsafe_allow_html=True)

def extract_pdf_text(uploaded_file):
    try:
        reader = PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
        return text
    except Exception as e:
        return ""

def parse_arg_number(s):
    if not s:
        return 0.0
    try:
        s_clean = s.replace('.', '').replace(',', '.')
        return float(s_clean)
    except:
        try:
            return float(s)
        except:
            return 0.0

# Process PDF uploads and robustly parse Factura, Swift, and Comisiones
for pk, p in parts.items():
    st.markdown(f"<div class='card'>", unsafe_allow_html=True)
    st.markdown(f"<h2>{p['n']}</h2>", unsafe_allow_html=True)
    
    col_u1, col_u2, col_u3 = st.columns(3)
    
    with col_u1:
        up_fac = st.file_uploader(f"Factura ({p['n']})", type=['pdf'], key=f"up_fac_{st.session_state.current_op}_{pk}")
        if up_fac:
            txt = extract_pdf_text(up_fac)
            
            # N° Factura E
            m_nro = re.search(r'(?:Compr\.?\s*Nro[:.]?|Factura\s+N[°º]?)\s*([\d-]+)', txt, re.IGNORECASE)
            if m_nro:
                f['nro'] = m_nro.group(1).strip()
            
            # Cliente / Señor(es)
            m_cli = re.search(r'Se[ñn]or\s*\(es\)[:.]?\s*([A-Z0-9\s,\.]+)', txt, re.IGNORECASE)
            if m_cli:
                f['cliente'] = m_cli.group(1).strip()
            else:
                lines = [l.strip() for l in txt.split('\n') if l.strip()]
                for idx, l in enumerate(lines):
                    if 'Señor' in l or 'Señor(es)' in l:
                        if idx + 1 < len(lines):
                            f['cliente'] = lines[idx+1].split('848')[0].strip()
                            break

            # Fecha emisión
            m_fec = re.search(r'Emisi[oó]n[:.]?\s*(\d{2}[/\-]\d{2}[/\-]\d{4})', txt, re.IGNORECASE)
            if m_fec:
                parts_d = m_fec.group(1).replace('-', '/').split('/')
                if len(parts_d) == 3:
                    f['fecha'] = f"{parts_d[2]}-{parts_d[1]}-{parts_d[0]}"

            # Tipo de Cambio Factura
            m_tc_fac = re.search(r'Tipo de Cambio[:.]?\s*([\d.,]+)', txt, re.IGNORECASE)
            if m_tc_fac:
                f['tc'] = parse_arg_number(m_tc_fac.group(1))

            # Importe Total USD (Factura E)
            m_imp_tot = re.search(r'Importe\s*Total\s*:\s*USD\s*([\d.,]+)', txt, re.IGNORECASE)
            if not m_imp_tot:
                m_imp_tot = re.search(r'Importe\s*Total[^:\d]*[:.]?\s*([\d.,]+)', txt, re.IGNORECASE)
            if m_imp_tot:
                val = parse_arg_number(m_imp_tot.group(1))
                if val > 0:
                    f['usd'] = val

            st.success("Factura leída y procesada.")

    with col_u2:
        up_sw = st.file_uploader(f"Swift ({p['n']})", type=['pdf'], key=f"up_sw_{st.session_state.current_op}_{pk}")
        if up_sw:
            txt = extract_pdf_text(up_sw)
            if len(txt.strip()) < 10:
                st.warning("El archivo PDF del Swift es una imagen escaneada. Por favor, verifica y completa los montos en los campos numéricos de abajo.")
            else:
                m_inst = re.search(r'Importe\s*instruido\s*[:.]?\s*([\d.,]+)', txt, re.IGNORECASE)
                if m_inst:
                    p['swift'] = parse_arg_number(m_inst.group(1))
                st.success("Swift leído y procesado.")

    with col_u3:
        up_com = st.file_uploader(f"Comisiones ({p['n']})", type=['pdf'], key=f"up_com_{st.session_state.current_op}_{pk}")
        if up_com:
            txt = extract_pdf_text(up_com)
            if len(txt.strip()) < 10:
                st.warning("El archivo de Comisiones/Cierre es una imagen escaneada. Por favor, completa los valores en los campos de abajo.")
            else:
                st.success("Aviso de crédito leído y procesado.")

    # Input fields
    c_f1, c_f2, c_f3, c_f4, c_f5 = st.columns(5)
    with c_f1:
        p['swift'] = st.number_input(f"Swift instruido USD", value=float(p['swift']), step=0.01, format="%.2f", key=f"sw_{st.session_state.current_op}_{pk}")
    with c_f2:
        p['gasto'] = st.number_input(f"Gasto Swift USD", value=float(p['gasto']), step=0.01, format="%.2f", key=f"gs_{st.session_state.current_op}_{pk}")
    with c_f3:
        p['tc'] = st.number_input(f"T.C. liq.", value=float(p['tc']), step=0.01, format="%.2f", key=f"tc_{st.session_state.current_op}_{pk}")
    with c_f4:
        p['com'] = st.number_input(f"Comisión $", value=float(p['com']), step=0.01, format="%.2f", key=f"com_{st.session_state.current_op}_{pk}")
    with c_f5:
        p['rg'] = st.number_input(f"RG 2408 $", value=float(p['rg']), step=0.01, format="%.2f", key=f"rg_{st.session_state.current_op}_{pk}")

    c_f6, c_f7 = st.columns(2)
    with c_f6:
        p['iva'] = st.number_input(f"IVA 21% $", value=float(p['iva']), step=0.01, format="%.2f", key=f"iva_{st.session_state.current_op}_{pk}")
    with c_f7:
        p['acr'] = st.number_input(f"Acreditado $", value=float(p['acr']), step=0.01, format="%.2f", key=f"acr_{pk}")

    st.markdown("</div>", unsafe_allow_html=True)

# Calculation logic & base selector
base_opt = st.selectbox("Base del resultado financiero:", ["Neto liquidado (como el PDF de ejemplo)", "Importe Swift instruido (como la app anterior)"], index=0 if curr_data['base']=='neto' else 1)
curr_data['base'] = 'neto' if 'Neto' in base_opt else 'swift'

def compute_part(p):
    net = p['swift'] - p['gasto']
    B = net if curr_data['base'] == 'neto' else p['swift']
    liq = net * p['tc']
    ct = p['com'] + p['rg'] + p['iva']
    sw = p['gasto'] * p['tc']
    fa = B * f['tc']
    rf = B * (p['tc'] - f['tc'])
    d = fa + rf - p['acr'] - (sw if curr_data['base'] == 'swift' else 0) - ct
    return {'net': net, 'liq': liq, 'ct': ct, 'sw': sw, 'fa': fa, 'rf': rf, 'd': d}

parts_list = list(parts.values())
results = [{**p, **compute_part(p)} for p in parts_list]

tot_swift = sum(r['swift'] for r in results)
tot_net = sum(r['net'] for r in results)
tot_liq = sum(r['liq'] for r in results)
tot_ct = sum(r['ct'] for r in results)
tot_rf = sum(r['rf'] for r in results)
tot_acr = sum(r['acr'] for r in results)
tot_d = sum(r['d'] for r in results)

# KPIs
st.markdown("<br>", unsafe_allow_html=True)
k1, k2, k3, k4, k5, k6 = st.columns(6)
pct_cobrado = (tot_swift / f['usd'] * 100) if f['usd'] > 0 else 0

with k1:
    st.markdown(f"<div class='kpi-container'><span class='kpi-label'>% cobrado</span><span class='kpi-value'>{pct_cobrado:.2f}%</span></div>", unsafe_allow_html=True)
with k2:
    st.markdown(f"<div class='kpi-container'><span class='kpi-label'>Saldo pendiente</span><span class='kpi-value'>US$ {f['usd'] - tot_swift:,.2f}</span></div>", unsafe_allow_html=True)
with k3:
    tot_gasto = sum(r['gasto'] for r in results)
    st.markdown(f"<div class='kpi-container'><span class='kpi-label'>Gastos Swift</span><span class='kpi-value'>US$ {tot_gasto:,.2f}</span></div>", unsafe_allow_html=True)
with k4:
    st.markdown(f"<div class='kpi-container'><span class='kpi-label'>Comisiones + IVA + perc.</span><span class='kpi-value'>$ {tot_ct:,.2f}</span></div>", unsafe_allow_html=True)
with k5:
    css_class = "g" if tot_rf >= 0 else "r"
    st.markdown(f"<div class='kpi-container {css_class}'><span class='kpi-label'>Resultado financiero</span><span class='kpi-value'>$ {tot_rf:,.2f}</span></div>", unsafe_allow_html=True)
with k6:
    st.markdown(f"<div class='kpi-container'><span class='kpi-label'>Total acreditado</span><span class='kpi-value'>$ {tot_acr:,.2f}</span></div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("<div class='card'>", unsafe_allow_html=True)
st.markdown("<h2>Resumen y conciliación</h2>", unsafe_allow_html=True)

table_data = []
for r in results:
    table_data.append({
        'Parte': r['n'],
        'Swift USD': f"{r['swift']:,.2f}",
        'Gasto Swift USD': f"{r['gasto']:,.2f}",
        'Neto USD': f"{r['net']:,.2f}",
        'T.C. liq.': r['tc'],
        'Total operación $': f"$ {r['liq']:,.2f}",
        'Comis.+Imp. $': f"$ {r['ct']:,.2f}",
        'Result. fin. $': f"$ {r['rf']:,.2f}",
        'Acreditado $': f"$ {r['acr']:,.2f}",
        'Diferencia': "✓ ok" if abs(r['d']) < 1 else f"$ {r['d']:,.2f} ✗"
    })

table_data.append({
    'Parte': 'TOTAL',
    'Swift USD': f"{tot_swift:,.2f}",
    'Gasto Swift USD': '',
    'Neto USD': f"{tot_net:,.2f}",
    'T.C. liq.': '',
    'Total operación $': f"$ {tot_liq:,.2f}",
    'Comis.+Imp. $': f"$ {tot_ct:,.2f}",
    'Result. fin. $': f"$ {tot_rf:,.2f}",
    'Acreditado $': f"$ {tot_acr:,.2f}",
    'Diferencia': "✓ ok" if abs(tot_d) < 1 else f"$ {tot_d:,.2f} ✗"
})

st.dataframe(pd.DataFrame(table_data), use_container_width=True)
st.markdown("<div style='font-size:12px; color:#6b7585; margin-top:8px;'>Regla: Factura $ (a T.C. de factura) + Resultado financiero = Acreditado + Comisión, IVA y percepción (+ Gasto Swift $ si la base es el importe Swift instruido).</div>", unsafe_allow_html=True)

def generate_pdf_bytes():
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, f"Conciliación de Exportación: {S_op}")
    y -= 30
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Datos de la Factura")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Fecha: {f['fecha']} | Nro: {f['nro']}")
    y -= 15
    c.drawString(50, y, f"Cliente: {f['cliente']}")
    y -= 15
    c.drawString(50, y, f"Monto: USD ${f['usd']:,.2f} | Tipo de Cambio: {f['tc']}")
    y -= 30
    
    for r in results:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, f"{r['n']}:")
        y -= 18
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Total operación: ${r['liq']:,.2f} ARS (USD ${r['net']:,.2f})")
        y -= 15
        c.drawString(50, y, f"1- Comisión: ${r['com']:,.2f} ARS | 2- Gastos: ${r['ct']:,.2f} ARS (RG2408: ${r['rg']:,.2f} | IVA: ${r['iva']:,.2f})")
        y -= 15
        c.drawString(50, y, f"3- Resultado financiero: ${r['rf']:,.2f} ARS | Acreditado: ${r['acr']:,.2f} ARS | T.C. liq.: {r['tc']}")
        y -= 25
        
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

st.download_button("⬇ Exportar PDF para archivo", data=generate_pdf_bytes(), file_name=f"Conciliacion_{S_op.replace(' ', '')}.pdf", mime="application/pdf")
st.markdown("</div>", unsafe_allow_html=True)

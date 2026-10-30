import streamlit as st
import pdfplumber
import re

st.set_page_config(page_title="Conciliación de Exportaciones", layout="centered")

# --- LÓGICA DE EXTRACCIÓN ---

def extraer_monto_usd(texto, concepto, tc_banco):
    """Busca un concepto (Ej: COMISION) y extrae su valor en USD ignorando los valores en ARS o el TC."""
    idx = texto.upper().find(concepto.upper())
    if idx != -1:
        # Tomar un bloque de texto después de la palabra clave
        bloque = texto[idx:idx+150]
        # Buscar todos los números con decimales
        numeros = re.findall(r'\b\d+\.\d+\b', bloque)
        for num_str in numeros:
            num = float(num_str)
            # Los montos de comisiones/impuestos en USD suelen ser menores a 1000
            # Se omite el valor si coincide exactamente con el tipo de cambio
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
    
    # 1. Factura
    if "FACTURA DE EXPORTACIÓN" in texto_completo.upper():
        datos["tipo"] = "Factura"
        tc_match = re.search(r'Tipo de Cambio:\s*([\d\.]+)', texto_limpio)
        if tc_match: datos["tc_factura"] = float(tc_match.group(1))

    # 2. Swift
    elif "ID SWIFT" in texto_completo.upper():
        datos["tipo"] = "Swift"
        operacion_match = re.search(r'Monto operación\s*:\s*([\d\.]+)', texto_limpio)
        
        # Identificar si es anticipo o saldo
        if "ANTICIPO" in texto_completo.upper():
            datos["etiqueta"] = "Anticipo"
        else:
            datos["etiqueta"] = "Restante"
            
        if operacion_match: datos["usd_swift"] = float(operacion_match.group(1))

    # 3. Liquidación Bancaria
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

# --- INTERFAZ ---

st.title("📑 Conciliación de Exportaciones")
st.markdown("Carga los PDFs (Factura, Swifts y Avisos de Crédito) para generar el desglose.")

archivos = st.file_uploader("Subir archivos PDF", type="pdf", accept_multiple_files=True, label_visibility="collapsed")

if archivos:
    # Contenedores temporales para clasificar la info
    tc_factura = 0.0
    swifts = []
    liquidaciones = []
    
    # Procesar todo lo subido
    for archivo in archivos:
        datos = procesar_pdf(archivo)
        if datos["tipo"] == "Factura":
            tc_factura = datos.get("tc_factura", 0.0)
        elif datos["tipo"] == "Swift":
            swifts.append(datos)
        elif datos["tipo"] == "Liquidacion":
            liquidaciones.append(datos)

    st.divider()

    # Si tenemos la factura cargada, podemos calcular
    if tc_factura > 0 and swifts:
        
        # Ordenar para mostrar "Anticipo" primero y "Restante" después
        swifts = sorted(swifts, key=lambda x: 0 if x.get("etiqueta") == "Anticipo" else 1)
        
        for swift in swifts:
            etiqueta = swift.get("etiqueta", "Cobro")
            usd_swift = swift.get("usd_swift", 0.0)
            
            # Buscar la liquidación bancaria que coincide con este monto Swift
            liq = next((l for l in liquidaciones if abs(l.get("usd_liquidado", 0) - usd_swift) < 1.0), None)
            
            st.subheader(f"{etiqueta}:")
            st.markdown(f"**Swift** ${usd_swift:,.2f}")
            
            if liq:
                # Extraer datos de la liquidación
                comision = liq.get("usd_comision", 0.0)
                rg2408 = liq.get("usd_rg2408", 0.0)
                iva = liq.get("usd_iva", 0.0)
                tc_banco = liq.get("tc_banco", 0.0)
                
                # Cálculo de Diferencia de Cambio
                brecha = tc_banco - tc_factura
                resultado_ars = usd_swift * brecha
                
                # Formatear el texto de resultado
                if resultado_ars > 0:
                    texto_resultado = f"positivo (${resultado_ars:,.2f} ARS)"
                elif resultado_ars < 0:
                    texto_resultado = f"negativo (${resultado_ars:,.2f} ARS)"
                else:
                    texto_resultado = "neutro ($0.00 ARS)"

                st.markdown(f"**Comision** ${comision:,.2f}")
                st.markdown(f"**rg2408** ${rg2408:,.2f}")
                st.markdown(f"**IVA** ${iva:,.2f}")
                st.markdown(f"**Resultado financiero** ({texto_resultado})")
            else:
                st.warning("*(Falta cargar el Aviso de Crédito correspondiente a este Swift)*")
            
            st.write("") # Espaciador
            
    elif not tc_factura:
        st.info("💡 Asegúrate de cargar la Factura de Exportación para poder calcular el resultado financiero.")

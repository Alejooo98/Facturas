import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import time
import tempfile
from io import BytesIO

# ==========================================
# CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Extractor Facturas", page_icon="🧾", layout="wide")

def obtener_api_key():
    try:
        return st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("❌ Error: No se encontró la API KEY en los Secrets.")
        st.stop()

api_key = obtener_api_key()
genai.configure(api_key=api_key)

# !!! AQUÍ ESTABA EL PROBLEMA. FORZAMOS EL MODELO FLASH !!!
MODELO_SOLIDO = "models/gemini-1.5-flash" 

# ==========================================
# LÓGICA
# ==========================================

def limpiar_json(texto_sucio):
    try:
        texto = texto_sucio.replace('```json', '').replace('```', '').strip()
        inicio = texto.find('{')
        fin = texto.rfind('}') + 1
        if inicio != -1 and fin != -1:
            return json.loads(texto[inicio:fin])
        else:
            return None
    except:
        return None

def procesar_factura_blindada(archivo_temporal):
    """Esta función tiene reintentos automáticos si sale error 429"""
    archivo_subido = None
    
    # 1. Subir archivo
    try:
        archivo_subido = genai.upload_file(archivo_temporal, mime_type="application/pdf")
        
        # Esperar a que procese
        intentos_espera = 0
        while archivo_subido.state.name == "PROCESSING":
            time.sleep(2)
            archivo_subido = genai.get_file(archivo_subido.name)
            intentos_espera += 1
            if intentos_espera > 20: return {'estado': 'ERROR', 'error_log': 'Timeout subida'}

    except Exception as e:
        return {'estado': 'ERROR', 'error_log': f"Error subiendo: {str(e)}"}

    # 2. Pedir datos a la IA (Con reintentos)
    modelo = genai.GenerativeModel(MODELO_SOLIDO)
    prompt = """
    Extrae en JSON: numero_contrato, nit_empresa, nombre_empresa, fecha_expedicion (YYYY-MM-DD), fecha_limite (YYYY-MM-DD), valor_pagar (numero).
    Si no existe, null.
    """

    MAX_REINTENTOS = 3
    for intento in range(MAX_REINTENTOS):
        try:
            respuesta = modelo.generate_content([archivo_subido, prompt])
            datos = limpiar_json(respuesta.text)
            
            # Si todo sale bien, limpiamos y retornamos
            try: genai.delete_file(archivo_subido.name)
            except: pass
            
            if datos:
                datos['estado'] = 'OK'
                return datos
            else:
                return {'estado': 'ERROR', 'error_log': 'JSON Inválido'}

        except Exception as e:
            error_msg = str(e)
            # Si es error de cuota (429), esperamos y reintentamos
            if "429" in error_msg or "quota" in error_msg.lower():
                time.sleep(15) # Espera larga de seguridad
                continue # Vuelve al inicio del loop
            else:
                # Si es otro error, fallamos
                try: genai.delete_file(archivo_subido.name)
                except: pass
                return {'estado': 'ERROR', 'error_log': str(e)}
    
    return {'estado': 'ERROR', 'error_log': 'Falló tras 3 intentos (Cuota excedida)'}

# ==========================================
# INTERFAZ
# ==========================================

st.title("🧾 Extractor de Facturas")

uploaded_files = st.file_uploader("Sube PDFs", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("Procesar"):
    resultados = []
    barra = st.progress(0)
    status = st.empty()
    
    total = len(uploaded_files)
    
    for i, pdf in enumerate(uploaded_files):
        status.text(f"Procesando {i+1}/{total}: {pdf.name}...")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf.getvalue())
            path = tmp.name
        
        datos = procesar_factura_blindada(path)
        datos['archivo'] = pdf.name
        
        if datos.get('estado') == 'ERROR':
            st.error(f"{pdf.name}: {datos.get('error_log')}")
        
        resultados.append(datos)
        os.unlink(path)
        
        barra.progress((i+1)/total)
        
        # FRENADO INTENCIONAL: Esperar 4 segundos entre facturas para no saturar
        time.sleep(4)

    status.success("¡Terminado!")

    if resultados:
        df = pd.DataFrame(resultados)
        st.dataframe(df)
        
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Descargar Excel", buffer, "Reporte.xlsx")

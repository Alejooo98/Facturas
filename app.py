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
        st.error("❌ Falta configurar el Secreto GOOGLE_API_KEY en Streamlit Cloud.")
        st.stop()

# Configurar API
api_key = obtener_api_key()
genai.configure(api_key=api_key)

# --- FUNCIÓN NUEVA PARA EVITAR EL ERROR 404 ---
def conseguir_modelo_disponible():
    """Pregunta a Google qué modelos tiene y elige el mejor disponible"""
    try:
        listado = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                listado.append(m.name)
        
        # Prioridad 1: Flash (Rápido y barato)
        for modelo in listado:
            if 'flash' in modelo and '1.5' in modelo:
                return modelo
        
        # Prioridad 2: Pro (Estándar)
        for modelo in listado:
            if 'pro' in modelo and '1.5' in modelo:
                return modelo
                
        # Prioridad 3: El que sea (Gemini 1.0)
        if listado:
            return listado[0]
            
        return "models/gemini-pro" # Fallback total
    except Exception as e:
        return "models/gemini-pro"

# Buscamos el modelo al inicio
MODELO_ACTUAL = conseguir_modelo_disponible()

# ==========================================
# LÓGICA DE EXTRACCIÓN
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

def subir_y_procesar(archivo_temporal):
    archivo_subido = None
    try:
        archivo_subido = genai.upload_file(archivo_temporal, mime_type="application/pdf")
        
        intentos = 0
        while archivo_subido.state.name == "PROCESSING":
            time.sleep(2)
            archivo_subido = genai.get_file(archivo_subido.name)
            intentos += 1
            if intentos > 30: return {'estado': 'ERROR', 'error_log': 'Timeout Google'}

        if archivo_subido.state.name == "FAILED":
             return {'estado': 'ERROR', 'error_log': 'Google falló al leer el PDF'}

        # Usamos el modelo que encontramos automáticamente
        modelo = genai.GenerativeModel(MODELO_ACTUAL)
        
        prompt = """
        Extrae datos de esta factura en JSON. Si no hay dato usa null.
        {
            "numero_contrato": "texto",
            "nit_empresa": "texto",
            "nombre_empresa": "texto",
            "fecha_expedicion": "YYYY-MM-DD",
            "fecha_limite": "YYYY-MM-DD",
            "valor_pagar": numero
        }
        """
        respuesta = modelo.generate_content([archivo_subido, prompt])
        datos = limpiar_json(respuesta.text)
        
        if datos:
            datos['estado'] = 'OK'
            try: genai.delete_file(archivo_subido.name)
            except: pass
            return datos
        else:
            return {'estado': 'ERROR', 'error_log': 'IA no devolvió JSON', 'raw': respuesta.text[:50]}

    except Exception as e:
        if archivo_subido:
            try: genai.delete_file(archivo_subido.name)
            except: pass
        return {'estado': 'ERROR', 'error_log': str(e)}

# ==========================================
# INTERFAZ
# ==========================================

st.title("🧾 Extractor de Facturas")

# Mostramos qué modelo se está usando (para que sepas cual funcionó)
st.caption(f"🤖 IA Conectada usando motor: `{MODELO_ACTUAL}`")

uploaded_files = st.file_uploader("Sube PDFs", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("Procesar"):
    resultados = []
    barra = st.progress(0)
    
    for i, pdf in enumerate(uploaded_files):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf.getvalue())
            path = tmp.name
        
        datos = subir_y_procesar(path)
        datos['archivo'] = pdf.name
        if datos.get('estado') == 'ERROR':
            st.error(f"{pdf.name}: {datos.get('error_log')}")
            
        resultados.append(datos)
        os.unlink(path)
        barra.progress((i+1)/len(uploaded_files))

    if resultados:
        df = pd.DataFrame(resultados)
        st.dataframe(df)
        
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Descargar Excel", buffer, "Reporte.xlsx")

import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import time
import tempfile
from io import BytesIO
from datetime import datetime

# ==========================================
# CONFIGURACIÓN DE LA PÁGINA
# ==========================================
st.set_page_config(page_title="Extractor de Facturas IA", page_icon="🧾", layout="wide")

# ==========================================
# LÓGICA (CONFIGURACIÓN DE SECRETOS)
# ==========================================

def obtener_api_key():
    """Intenta obtener la API KEY de los secretos de Streamlit"""
    try:
        # Busca en la caja fuerte de la nube
        return st.secrets["GOOGLE_API_KEY"]
    except FileNotFoundError:
        st.error("❌ NO SE ENCONTRÓ LA API KEY. Configura los 'Secrets' en Streamlit Cloud.")
        st.stop()
    except KeyError:
        st.error("❌ La clave 'GOOGLE_API_KEY' no está definida en los secretos.")
        st.stop()

# --- CONFIGURACIÓN AUTOMÁTICA (INVISIBLE AL USUARIO) ---
api_key = obtener_api_key()
genai.configure(api_key=api_key)


# ==========================================
# FUNCIONES DE PROCESAMIENTO
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

def subir_y_procesar(archivo_temporal, modelo_nombre):
    archivo_subido = None
    try:
        archivo_subido = genai.upload_file(archivo_temporal, mime_type="application/pdf")
        
        intentos = 0
        while archivo_subido.state.name == "PROCESSING":
            time.sleep(2)
            archivo_subido = genai.get_file(archivo_subido.name)
            intentos += 1
            if intentos > 20: return {'estado': 'ERROR', 'error_log': 'Timeout Google'}

        if archivo_subido.state.name == "FAILED":
             return {'estado': 'ERROR', 'error_log': 'Fallo procesamiento Google'}

        modelo = genai.GenerativeModel(modelo_nombre)
        
        prompt = """
        Actúa como contable experto. Extrae datos en JSON. Si no existe usa null.
        Estructura:
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
        datos_limpios = limpiar_json(respuesta.text)
        
        if datos_limpios:
            datos_limpios['estado'] = 'OK'
            try: genai.delete_file(archivo_subido.name)
            except: pass
            return datos_limpios
        else:
            return {'estado': 'ERROR', 'error_log': 'JSON Inválido', 'raw': respuesta.text[:50]}

    except Exception as e:
        if archivo_subido:
            try: genai.delete_file(archivo_subido.name)
            except: pass
        return {'estado': 'ERROR', 'error_log': str(e)}

# ==========================================
# INTERFAZ (LIMPIA, SIN PEDIR CLAVES)
# ==========================================

st.title("🧾 Extractor de Facturas")
st.info("Sistema listo para procesar. La IA está conectada internamente.")

uploaded_files = st.file_uploader("Sube tus PDFs aquí", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("🚀 Procesar"):
    
    resultados = []
    barra = st.progress(0)
    caja_info = st.empty()
    total = len(uploaded_files)

    for i, uploaded_file in enumerate(uploaded_files):
        caja_info.text(f"Leyendo: {uploaded_file.name}...")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        datos = subir_y_procesar(tmp_path, "gemini-1.5-flash")
        datos['archivo'] = uploaded_file.name
        
        if datos.get('estado') == 'ERROR':
            st.error(f"Fallo en {uploaded_file.name}: {datos.get('error_log')}")
        
        resultados.append(datos)
        os.unlink(tmp_path)
        barra.progress((i + 1) / total)

    caja_info.success("¡Listo!")
    
    if resultados:
        df = pd.DataFrame(resultados)
        cols = ['archivo', 'estado', 'nombre_empresa', 'valor_pagar', 'fecha_limite', 'nit_empresa', 'numero_contrato', 'error_log']
        cols_finales = [c for c in cols if c in df.columns]
        df = df[cols_finales]

        st.dataframe(df)
        
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
            
        st.download_button("📥 Descargar Excel", buffer.getvalue(), "Facturas.xlsx", "application/vnd.ms-excel")

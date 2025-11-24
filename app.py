import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import os
import time
import tempfile
from io import BytesIO

st.set_page_config(page_title="Extractor Facturas", page_icon="🧾", layout="wide")

# 1. CONFIGURACIÓN API KEY
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
except:
    st.error("❌ Falta la API KEY en los Secrets de Streamlit.")
    st.stop()

# 2. TU LÓGICA ORIGINAL (Restaurada y mejorada)
def seleccionar_modelo_optimo():
    """
    Busca el mejor modelo disponible en este orden:
    1. Flash 1.5 (Ideal)
    2. Cualquier Flash (Rápido)
    3. Pro 1.5 (Potente)
    4. gemini-pro (Viejo confiable)
    """
    try:
        modelos_disponibles = list(genai.list_models())
        nombres = [m.name for m in modelos_disponibles if 'generateContent' in m.supported_generation_methods]
        
        # Prioridad 1: Gemini 1.5 Flash
        for m in nombres:
            if 'flash' in m and '1.5' in m: return m
            
        # Prioridad 2: Cualquier versión Flash
        for m in nombres:
            if 'flash' in m: return m

        # Prioridad 3: Gemini 1.5 Pro
        for m in nombres:
            if 'pro' in m and '1.5' in m: return m
            
        # Prioridad 4: Gemini Pro Clásico
        return 'models/gemini-pro'
        
    except Exception as e:
        # Si falla el listado, vamos a lo seguro
        return 'models/gemini-pro'

# Ejecutamos la selección
MODELO_ACTUAL = seleccionar_modelo_optimo()

# ==========================================
# INTERFAZ
# ==========================================
st.title("🧾 Extractor de Facturas")

# Mostramos qué modelo ganó la elección
if "flash" in MODELO_ACTUAL:
    st.success(f"⚡ Modo Rápido Activado: Usando **{MODELO_ACTUAL}**")
else:
    st.warning(f"🐢 Modo Estándar: Usando **{MODELO_ACTUAL}** (Flash no encontrado)")

# ==========================================
# PROCESAMIENTO
# ==========================================
def limpiar_json(texto_sucio):
    try:
        texto = texto_sucio.replace('```json', '').replace('```', '').strip()
        inicio = texto.find('{')
        fin = texto.rfind('}') + 1
        if inicio != -1 and fin != -1:
            return json.loads(texto[inicio:fin])
        return None
    except:
        return None

def procesar(path_pdf):
    try:
        # Subir
        archivo = genai.upload_file(path_pdf, mime_type="application/pdf")
        while archivo.state.name == "PROCESSING":
            time.sleep(1)
            archivo = genai.get_file(archivo.name)

        # Generar con el modelo seleccionado
        modelo = genai.GenerativeModel(MODELO_ACTUAL)
        
        prompt = """
        Extrae JSON: numero_contrato, nit_empresa, nombre_empresa, fecha_expedicion, fecha_limite, valor_pagar.
        Si no existe: null. Fechas: YYYY-MM-DD.
        """

        # Intentos (Solo 2 para ser rápido, pero con pausa si hay error de cuota)
        for i in range(2):
            try:
                res = modelo.generate_content([archivo, prompt])
                datos = limpiar_json(res.text)
                
                try: genai.delete_file(archivo.name)
                except: pass
                
                if datos:
                    datos['estado'] = 'OK'
                    return datos
            except Exception as e:
                if "429" in str(e): # Cuota llena
                    time.sleep(5)
                    continue
                else:
                    pass # Probar siguiente intento

        return {'estado': 'ERROR', 'error_log': 'Fallo tras intentos'}

    except Exception as e:
        return {'estado': 'ERROR', 'error_log': str(e)}

# --- SUBIDA ---
uploaded_files = st.file_uploader("Sube PDFs", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("Procesar"):
    resultados = []
    barra = st.progress(0)
    
    for i, pdf in enumerate(uploaded_files):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf.getvalue())
            path = tmp.name
            
        datos = procesar(path)
        datos['archivo'] = pdf.name
        resultados.append(datos)
        os.unlink(path)
        
        if datos.get('estado') == 'ERROR':
            st.error(f"{pdf.name}: {datos.get('error_log')}")
            
        barra.progress((i+1)/len(uploaded_files))
        time.sleep(1) # Pequeña pausa de cortesía

    if resultados:
        df = pd.DataFrame(resultados)
        st.dataframe(df)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Descargar Excel", buffer, "Reporte.xlsx")

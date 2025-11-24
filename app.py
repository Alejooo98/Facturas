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

# --- CAMBIO IMPORTANTE: SOLO EL NOMBRE CORTO ---
MODELO_USAR = "gemini-1.5-flash" 

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

def procesar_factura(archivo_temporal):
    archivo_subido = None
    try:
        # 1. Subir
        archivo_subido = genai.upload_file(archivo_temporal, mime_type="application/pdf")
        
        # Esperar procesamiento
        espera = 0
        while archivo_subido.state.name == "PROCESSING":
            time.sleep(2)
            archivo_subido = genai.get_file(archivo_subido.name)
            espera += 1
            if espera > 20: return {'estado': 'ERROR', 'error_log': 'Timeout subida'}

    except Exception as e:
        return {'estado': 'ERROR', 'error_log': f"Error subiendo: {str(e)}"}

    # 2. Generar (Con reintentos para evitar bloqueos)
    modelo = genai.GenerativeModel(MODELO_USAR)
    prompt = """
    Extrae datos en JSON. Campos: numero_contrato, nit_empresa, nombre_empresa, fecha_expedicion (YYYY-MM-DD), fecha_limite (YYYY-MM-DD), valor_pagar (numero).
    Si no hay dato, usa null.
    """

    for i in range(3): # 3 Intentos
        try:
            respuesta = modelo.generate_content([archivo_subido, prompt])
            datos = limpiar_json(respuesta.text)
            
            # Limpiar y salir
            try: genai.delete_file(archivo_subido.name)
            except: pass
            
            if datos:
                datos['estado'] = 'OK'
                return datos
            else:
                return {'estado': 'ERROR', 'error_log': 'JSON invalido'}
                
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep(10) # Esperar si hay bloqueo
                continue
            elif "404" in str(e):
                # Si sigue saliendo 404, es fallo critico del modelo
                try: genai.delete_file(archivo_subido.name)
                except: pass
                return {'estado': 'ERROR', 'error_log': f"Modelo no encontrado: {MODELO_USAR}"}
            else:
                try: genai.delete_file(archivo_subido.name)
                except: pass
                return {'estado': 'ERROR', 'error_log': str(e)}

    return {'estado': 'ERROR', 'error_log': 'Fallo por cuota (Intentos agotados)'}

# ==========================================
# INTERFAZ
# ==========================================
st.title("🧾 Extractor de Facturas")

uploaded_files = st.file_uploader("Sube PDFs", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("Procesar"):
    resultados = []
    barra = st.progress(0)
    
    for i, pdf in enumerate(uploaded_files):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf.getvalue())
            path = tmp.name
        
        datos = procesar_factura(path)
        datos['archivo'] = pdf.name
        
        if datos.get('estado') == 'ERROR':
            st.error(f"{pdf.name}: {datos.get('error_log')}")
        else:
            st.success(f"Leído: {pdf.name}")
            
        resultados.append(datos)
        os.unlink(path)
        barra.progress((i+1)/len(uploaded_files))
        time.sleep(2) # Pausa pequeña

    if resultados:
        df = pd.DataFrame(resultados)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        st.download_button("Descargar Excel", buffer, "Reporte.xlsx")

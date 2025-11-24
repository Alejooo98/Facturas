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
# LÓGICA (Tu código adaptado)
# ==========================================

def configurar_ia(api_key):
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        st.error(f"Error configurando API: {e}")
        return False

def subir_y_procesar(archivo_temporal, modelo_nombre):
    """Sube el archivo a Gemini y extrae datos"""
    archivo_subido = None
    try:
        # Subir a Google
        archivo_subido = genai.upload_file(archivo_temporal, mime_type="application/pdf")
        
        # Esperar procesamiento
        while archivo_subido.state.name == "PROCESSING":
            time.sleep(1)
            archivo_subido = genai.get_file(archivo_subido.name)

        # Generar contenido
        modelo = genai.GenerativeModel(modelo_nombre)
        
        prompt = """
        Analiza esta factura y extrae los siguientes datos en formato JSON estricto.
        Si un dato no aparece, usa null. Usa formato ISO para fechas (YYYY-MM-DD).
        
        Campos requeridos:
        1. numero_contrato: (Busca cuenta, referencia o contrato)
        2. nit_empresa: (Solo números y guiones)
        3. nombre_empresa: (Ej: Claro, Movistar, Enel)
        4. fecha_expedicion
        5. fecha_limite
        6. valor_pagar: (Número decimal puro, sin símbolos $)
        """

        respuesta = modelo.generate_content([archivo_subido, prompt])
        
        # Limpieza JSON
        texto_limpio = respuesta.text.replace('```json', '').replace('```', '').strip()
        start = texto_limpio.find('{')
        end = texto_limpio.rfind('}') + 1
        json_final = json.loads(texto_limpio[start:end])
        
        json_final['estado'] = 'OK'
        
        # Limpiar nube
        genai.delete_file(archivo_subido.name)
        return json_final

    except Exception as e:
        if archivo_subido:
            try: genai.delete_file(archivo_subido.name)
            except: pass
        return {'estado': 'ERROR', 'error_log': str(e)}

# ==========================================
# INTERFAZ DE USUARIO (FRONTEND)
# ==========================================

st.title("🧾 Extractor Inteligente de Facturas")
st.markdown("Sube tus PDFs y la IA extraerá la información clave a Excel.")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("Configuración")
    # Input seguro para la API Key (tipo password para que no se vea)
    api_key_input = st.text_input("Tu API Key de Google Gemini", type="password")
    
    if not api_key_input:
        st.warning("Por favor ingresa tu API Key para empezar.")
        st.stop() # Detiene la ejecución hasta que haya clave

    st.info("Modelo: Gemini 1.5 Flash (Automático)")

# Configurar IA con la clave ingresada por el usuario
configurar_ia(api_key_input)

# --- ZONA DE CARGA ---
uploaded_files = st.file_uploader("Arrastra tus facturas aquí (PDF)", type="pdf", accept_multiple_files=True)

if uploaded_files:
    st.success(f"Se han cargado {len(uploaded_files)} archivos.")
    
    if st.button("🚀 Procesar Facturas"):
        resultados = []
        barra_progreso = st.progress(0)
        status_text = st.empty()
        
        total_archivos = len(uploaded_files)

        for i, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Analizando: {uploaded_file.name}...")
            
            # Streamlit tiene el archivo en memoria, Gemini necesita un path o bytes
            # Creamos un archivo temporal en el disco
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            # Llamar a la IA
            datos = subir_y_procesar(tmp_path, "gemini-1.5-flash")
            datos['archivo'] = uploaded_file.name
            resultados.append(datos)
            
            # Borrar archivo temporal del disco local
            os.unlink(tmp_path)
            
            # Actualizar barra
            barra_progreso.progress((i + 1) / total_archivos)

        status_text.text("✅ ¡Proceso completado!")
        
        # --- RESULTADOS ---
        df = pd.DataFrame(resultados)
        
        # Reordenar columnas si existen
        cols_deseadas = ['archivo', 'estado', 'nombre_empresa', 'nit_empresa', 
                         'numero_contrato', 'fecha_expedicion', 'fecha_limite', 'valor_pagar']
        cols_finales = [c for c in cols_deseadas if c in df.columns]
        df = df[cols_finales]

        st.subheader("Vista Previa de Resultados")
        st.dataframe(df)

        # --- DESCARGA EXCEL ---
        # Crear Excel en memoria RAM (buffer)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Facturas')
            
        st.download_button(
            label="📥 Descargar Reporte Excel",
            data=buffer.getvalue(),
            file_name=f"Reporte_Facturas_{datetime.now().strftime('%H%M')}.xlsx",
            mime="application/vnd.ms-excel"
        )
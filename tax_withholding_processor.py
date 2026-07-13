#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Procesador de Comprobantes de Retención IVA - SENIAT
Orden: NVIDIA → MISTRAL → QWEN | Validación EXACTA + Números Puros + Monitor de Red
"""
import os
import io
import re
import json
import base64
import shutil
import requests
import subprocess
import pandas as pd
import tkinter as tk
from tkinter import filedialog
from dotenv import load_dotenv
import pypdfium2 as pdfium
from PIL import Image

# ==========================================
# CONSTANTES Y ESTILOS
# ==========================================
ROJO = '\033[91m'
VERDE = '\033[92m'
AMARILLO = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'

API_TIMEOUT = 120  # Timeout único, sin reintentos

# Prompt Fiscal Agresivo (Transcripción literal + limpieza numérica)
PROMPT_FISCAL = """
Eres un auditor fiscal experto en extracción de datos de comprobantes de retención de IVA del SENIAT (Venezuela).
Tu única tarea es transcribir TODOS los datos visibles del documento a un JSON estricto.

🚨 INSTRUCCIONES CRÍTICAS DE LECTURA:
1. LEE EL DOCUMENTO COMPLETO, de arriba hacia abajo, de izquierda a derecha. NO te saltes el encabezado, la tabla central ni el pie de página.
2. Extrae OBLIGATORIAMENTE cada clave listada abajo. Si un campo no es visible, está borroso o no aplica, usa cadena vacía "". NUNCA omitas una clave.
3. 'numero_control': Alfanumérico. Cópialo EXACTAMENTE como aparece. Sin modificar.
4. 'numero_comprobante': 14 dígitos (AAAAMMSSSSSSSS). Si lo ves, extraelo. Si no, "".
5. Fechas y Montos: 🚫 REGLA DE LIMPIEZA: En los campos numéricos (total, base, iva, retenido), NUNCA incluyas "Bs.", "$" o textos. Solo extrae dígitos, comas y puntos (ej: "66476,91").
6. RIFs: Incluye guiones y letras (ej: "J-40488758-0").
7. Imprenta: Si no existe sección de impresor en el documento, deja "" en ambos campos.
8. 🚫 NO COPIES DATOS: Nunca copies el nombre/RIF del Agente en el Proveedor. Si el Proveedor no se ve, déjalo vacío.

🔑 CLAVES JSON REQUERIDAS (EN ESTE ORDEN EXACTO):
- "numero_comprobante": ""
- "agente_nombre": ""
- "agente_rif": ""
- "proveedor_nombre": ""
- "proveedor_rif": ""
- "fecha_emision": ""
- "fecha_entrega": ""
- "numero_factura": ""
- "numero_control": ""
- "monto_total": ""
- "base_imponible": ""
- "impuesto_iva": ""
- "iva_retenido": ""
- "impresor_nombre": ""
- "impresor_rif": ""

FORMATO DE SALIDA:
Devuelve ÚNICAMENTE un array JSON válido: [ { ... } ]
CERO texto explicativo. CERO markdown. CERO prefijos.
Si el documento está vacío o es irreconocible, devuelve: []
"""

# ==========================================
# LIMPIEZA Y VALIDACIÓN FISCAL
# ==========================================

def limpiar_numeros_puros(df):
    """
    Convierte campos monetarios a números puros listos para cálculo.
    Elimina 'Bs.', '$', espacios, puntos de miles y estandariza decimales.
    Ejemplo: "66.476,91" -> 66476.91 (float)
    """
    cols_numericas = ["monto_total", "base_imponible", "impuesto_iva", "iva_retenido"]
    for col in cols_numericas:
        if col in df.columns:
            def clean(val):
                s = str(val).replace("Bs.", "").replace("$", "").replace(" ", "").strip()
                if not s: return ""
                # Formato venezolano: 1.000,00 -> 1000.00
                if "," in s:
                    ent, dec = s.rsplit(",", 1)
                    return ent.replace(".", "") + "." + dec
                else:
                    return s.replace(".", "")
            df[col] = df[col].apply(clean)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna("")
    return df

def validar_fila_seniat(fila):
    """
    Valida integridad fiscal y matemática con EXACTITUD ABSOLUTA.
    Incluye detección de texto en campos numéricos, caracteres sospechosos en control,
    auto-retención y duplicidad de control/factura.
    Retorna: (ESTADO, [lista_de_alertas])
    """
    alertas = []
    
    def get(k):
        val = fila.get(k, "")
        return str(val).strip() if val is not None else ""
    
    def to_float(k):
        raw = get(k).replace(",", ".").replace("Bs.", "").strip()
        try:
            return float(raw) if raw else 0.0
        except:
            return None

    # 1. CAMPOS CRÍTICOS VACÍOS (Obligatorios según Providencia)
    criticos = [
        "numero_comprobante", "agente_rif", "proveedor_rif", 
        "numero_control", "base_imponible", "impuesto_iva", "iva_retenido"
    ]
    for campo in criticos:
        if not get(campo):
            alertas.append(f"{campo} vacío")
    
    # 2. VALIDACIÓN DE FORMATO: 14 DÍGITOS en numero_comprobante
    comp = get("numero_comprobante")
    if comp and len(comp) != 14:
        alertas.append(f"Comprobante tiene {len(comp)} dígitos (debe ser 14)")
    
    # 3. VALIDACIÓN MATEMÁTICA EXACTA (SIN TOLERANCIA)
    base = to_float("base_imponible")
    iva = to_float("impuesto_iva")
    total = to_float("monto_total")
    retenido = to_float("iva_retenido")
    
    if base is not None and iva is not None and total is not None:
        # Regla A: Base + IVA = Total (Exacto, diferencia > 0.00)
        if base > 0 and iva > 0 and abs((base + iva) - total) > 0.00:
            alertas.append(f"Descuadre exacto: Base+IVA ≠ Total")
        
        # Regla B: IVA debe ser exactamente el 16% de la Base (Sin tolerancia)
        if base > 0 and iva > 0:
            iva_esperado = round(base * 0.16, 2)
            if abs(iva - iva_esperado) > 0.00:
                alertas.append(f"IVA no es 16% exacto de la base")
        
        # Regla C: Retenido no puede superar el IVA causado
        if retenido is not None and retenido > iva and iva > 0:
            alertas.append(f"Retenido supera el IVA")

    # 4. DETECCIÓN DE "BASURA" EN CAMPOS NUMÉRICOS
    campos_numericos = ["monto_total", "base_imponible", "impuesto_iva", "iva_retenido"]
    for campo in campos_numericos:
        val = get(campo)
        if val and ("Bs." in val or "%" in val or any(ch.isalpha() for ch in val if ch.lower() not in 'e')):
            alertas.append(f"{campo} contiene texto no numérico")

    # 5. CARACTERES SOSPECHOSOS EN NÚMERO DE CONTROL
    ctrl = get("numero_control")
    if ctrl and re.match(r"^[ZzOo]", ctrl):
        alertas.append("Nº Control empieza con carácter sospechoso (verificar OCR)")

    # 6. VALIDACIÓN LÓGICA: Auto-retención (Imposible legalmente)
    rif_agente = get("agente_rif")
    rif_prov = get("proveedor_rif")
    if rif_agente and rif_prov and rif_agente == rif_prov:
        alertas.append("Error: RIF del Agente y Proveedor son iguales (Auto-retención)")

    # 7. VALIDACIÓN LÓGICA: Control igual a Factura (Error común de copia)
    factura = get("numero_factura")
    if ctrl and factura and ctrl == factura:
        alertas.append("Error: Nº Control es igual al Nº Factura")

    # 8. FORMATO RIF (Validación básica de estructura)
    rif_pat = re.compile(r"^[VEJPG]-\d{7,8}-\d$")
    for rif_c in ["agente_rif", "proveedor_rif"]:
        v = get(rif_c)
        if v and not rif_pat.match(v):
            alertas.append(f"RIF inválido ({rif_c})")
    
    return ("REVISAR" if alertas else "APROBADO"), alertas

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================

def inicializar_entorno():
    """Carga las variables desde accesoimagen.env"""
    load_dotenv("accesoimagen.env", override=True)
    return {
        "NVIDIA": os.getenv("NVIDIA_API_KEY"),
        "MISTRAL": os.getenv("MISTRAL_API_KEY"),
        "QWEN": os.getenv("QWEN_API_KEY")
    }

def imagen_a_base64(ruta_imagen):
    """Convierte imagen a base64, forzando PNG para compatibilidad."""
    try:
        img = Image.open(ruta_imagen)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
    except Exception:
        ext = os.path.splitext(ruta_imagen)[1].lower().replace('.', '')
        mime = 'image/jpeg' if ext in ['jpg', 'jpeg'] else 'image/png'
        with open(ruta_imagen, "rb") as f:
            return f"data:{mime};base64,{base64.b64encode(f.read()).decode('utf-8')}"

def pdf_a_base64_imagenes(ruta_pdf):
    """Convierte PDF a lista de imágenes base64."""
    imagenes_base64 = []
    doc = pdfium.PdfDocument(ruta_pdf)
    for i in range(len(doc)):
        bitmap = doc[i].render(scale=2)
        buffer = io.BytesIO()
        bitmap.to_pil().save(buffer, format="PNG")
        imagenes_base64.append(f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}")
    return imagenes_base64

def extraer_json_de_respuesta(texto):
    """Parser robusto para obtener JSON de respuestas de LLM."""
    texto = texto.strip()
    for fence in ["```json", "```"]:
        if texto.startswith(fence):
            texto = texto[len(fence):]
    if texto.endswith("```"):
        texto = texto[:-3]
    texto = texto.strip()
    
    try:
        return json.loads(texto)
    except:
        pass
    
    idx_ini, idx_fin = texto.find('['), texto.rfind(']')
    if idx_ini != -1 and idx_fin != -1 and idx_fin > idx_ini:
        try:
            return json.loads(texto[idx_ini:idx_fin+1])
        except:
            pass
            
    patron = r'\{[^{}]*"numero_control"[^{}]*\}'
    coincidencias = re.findall(patron, texto, re.DOTALL)
    resultados = []
    for c in coincidencias:
        try:
            resultados.append(json.loads(c))
        except:
            continue
    return resultados if resultados else []

# ==========================================
# PROVEEDORES (CON MONITOREO DE RED)
# ==========================================

def proveedor_llm_generico(url, headers, payload, proveedor_nombre, nombre_archivo, num_pagina):
    """Llama a la API UNA SOLA VEZ. Sin bucles de reintento. Con monitoreo de red."""
    try:
        print(f"      {CYAN}→ {proveedor_nombre}...{RESET}")
        response = requests.post(url, headers=headers, json=payload, timeout=API_TIMEOUT)
        
        if response.status_code == 429:
            print(f"      {AMARILLO}⏳ Rate limit. Saltando...{RESET}")
            return []
            
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text[:80]}")
        
        # Debug mode: guarda respuesta cruda para análisis
        if os.getenv("DEBUG_MODE", "false").lower() == "true":
            txt = response.json()["choices"][0]["message"]["content"]
            with open(f"debug_{nombre_archivo}_{proveedor_nombre}.txt", "w", encoding="utf-8") as f:
                f.write(txt)
        
        contenido = response.json()["choices"][0]["message"]["content"]
        return extraer_json_de_respuesta(contenido)
        
    except requests.exceptions.ConnectionError:
        print(f"      {ROJO}🔌 ERROR DE RED/INTERNET al contactar {proveedor_nombre}{RESET}")
        return []
    except requests.exceptions.Timeout:
        print(f"      {ROJO}⏱️ TIMEOUT DE RED en {proveedor_nombre}{RESET}")
        return []
    except Exception as e:
        print(f"      {ROJO}✗ ERROR {proveedor_nombre}: {e}{RESET}")
        return []

def proveedor_nvidia(img_url, api_key, nombre_archivo, num_pagina):
    """NVIDIA Llama 3.2 Vision"""
    return proveedor_llm_generico(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        {"model": "meta/llama-3.2-11b-vision-instruct", "messages": [{"role":"user", "content":[
            {"type":"text", "text": PROMPT_FISCAL}, {"type":"image_url", "image_url":{"url": img_url}}
        ]}], "max_tokens": 4096, "temperature": 0.05},
        "NVIDIA", nombre_archivo, num_pagina
    )

def proveedor_mistral(img_url, api_key, nombre_archivo, num_pagina):
    """Mistral Large 3 vía infraestructura NVIDIA."""
    return proveedor_llm_generico(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        {"model": "mistralai/mistral-large-3-675b-instruct-2512", "messages": [{"role":"user", "content":[
            {"type":"text", "text": PROMPT_FISCAL}, {"type":"image_url", "image_url":{"url": img_url}}
        ]}], "max_tokens": 4096, "temperature": 0.15},
        "MISTRAL", nombre_archivo, num_pagina
    )

def proveedor_qwen(img_url, api_key, nombre_archivo, num_pagina):
    """Qwen 3.5 Flash vía DashScope International"""
    return proveedor_llm_generico(
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        {"model": "qwen3.5-flash", "messages": [{"role":"user", "content":[
            {"type":"text", "text": PROMPT_FISCAL}, {"type":"image_url", "image_url":{"url": img_url}}
        ]}], "max_tokens": 4096, "temperature": 0.05, "response_format": {"type":"json_object"}},
        "QWEN", nombre_archivo, num_pagina
    )

# ==========================================
# ORQUESTADOR Y FLUJO
# ==========================================

def extraer_con_fallback(img_url, num_pagina, nombre_archivo, api_keys):
    orden = os.getenv("FALLBACK_ORDER", "NVIDIA,MISTRAL,QWEN").split(",")
    
    mapa = {
        "NVIDIA": lambda: proveedor_nvidia(img_url, api_keys.get("NVIDIA"), nombre_archivo, num_pagina) if api_keys.get("NVIDIA") else None,
        "MISTRAL": lambda: proveedor_mistral(img_url, api_keys.get("MISTRAL"), nombre_archivo, num_pagina) if api_keys.get("MISTRAL") else None,
        "QWEN": lambda: proveedor_qwen(img_url, api_keys.get("QWEN"), nombre_archivo, num_pagina) if api_keys.get("QWEN") else None
    }

    for prov in [p.strip() for p in orden if p.strip()]:
        if prov in mapa:
            try:
                res = mapa[prov]()
                if res and len(res) > 0:
                    print(f"      {VERDE}✓ {prov} exitoso: {len(res)} registro(s){RESET}")
                    return res
                else:
                    print(f"      {AMARILLO}⚠ {prov} sin datos. Siguiente...{RESET}")
            except Exception as e:
                print(f"      {ROJO}✗ {prov} falló: {e}. Siguiente...{RESET}")
    
    print(f"      {ROJO}✗ Todos los proveedores fallaron.{RESET}")
    return []

def procesar_comprobantes():
    api_keys = inicializar_entorno()
    if not any(api_keys.values()):
        print(f"{ROJO}Error: Configura tus claves en accesoimagen.env{RESET}")
        return

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    rutas = filedialog.askopenfilenames(title="Seleccionar Archivos", filetypes=[("Archivos", "*.pdf;*.webp;*.png;*.jpg;*.jpeg")])
    if not rutas:
        return

    print(f"\n{VERDE}📂 Procesando {len(rutas)} archivo(s)...{RESET}")
    datos = []
    
    for i, ruta in enumerate(rutas, 1):
        nombre = os.path.basename(ruta)
        print(f"\n[{i}/{len(rutas)}] {nombre}")
        try:
            imgs = pdf_a_base64_imagenes(ruta) if ruta.lower().endswith('.pdf') else [imagen_a_base64(ruta)]
        except Exception as e:
            print(f"  {ROJO}Error cargando archivo: {e}{RESET}")
            continue
            
        for idx, img in enumerate(imgs, 1):
            try:
                res = extraer_con_fallback(img, idx, nombre, api_keys)
                if res and isinstance(res, list):
                    for item in res:
                        if isinstance(item, dict):
                            datos.append(item)
            except Exception:
                continue

    if not datos: 
        print(f"\n{AMARILLO}Sin datos válidos.{RESET}")
        return

    # ==========================================
    # PROCESAMIENTO, LIMPIEZA Y VALIDACIÓN
    # ==========================================
    df = pd.DataFrame(datos)
    
    # 1. Limpiar números para cálculo puro (Convierte "66.476,91" a 66476.91)
    df = limpiar_numeros_puros(df)
    
    # 2. Validar fila por fila
    estados, alertas_tot = [], []
    for _, fila in df.iterrows():
        est, errs = validar_fila_seniat(fila)
        estados.append(est)
        alertas_tot.extend(errs)
    
    df['REVISION'] = estados

    # Reporte en terminal
    aprob = sum(1 for e in estados if e == "APROBADO")
    rev = len(estados) - aprob
    print(f"\n{CYAN}📊 Validación Automática EXACTA:{RESET}")
    print(f"  ✅ Aprobados: {aprob} | ️ Revisar: {rev}")
    if alertas_tot:
        alertas_unicas = list(set(alertas_tot))[:3]
        print(f"  {AMARILLO} Alertas detectadas: {', '.join(alertas_unicas)}...{RESET}")

    # Limpieza mínima de control (quitar puntos y espacios residuales)
    if 'numero_control' in df.columns:
        df['numero_control'] = df['numero_control'].astype(str).str.replace(r'[\. ]', '', regex=True)

    # Generar borrador temporal
    temp_file = "temp_retenciones.xlsx"
    try:
        df.to_excel(temp_file, index=False)
        if shutil.which('code'): 
            subprocess.Popen(['code', temp_file], shell=True)
        else: 
            print(f"{AMARILLO}VS Code no detectado. Archivo guardado como '{temp_file}'{RESET}")
    except Exception as e:
        print(f"{ROJO}Error guardando temporal: {e}{RESET}")
        return

    # Decisión de guardado
    if input("\n¿Guardar datos finales? (s/n): ").lower() == 's':
        final = input("Nombre final (sin extensión): ") or "Retenciones"
        dest = os.path.join(os.path.dirname(rutas[0]), f"{final}.xlsx")
        shutil.copy2(temp_file, dest)
        print(f"{VERDE}✅ Guardado en: {dest}{RESET}")
    
    # Autodestrucción del temporal
    try:
        os.remove(temp_file)
    except PermissionError:
        print(f"{AMARILLO}⚠ No se eliminó el temporal (cierra la pestaña en VS Code){RESET}")
    except Exception:
        pass

if __name__ == "__main__":
    procesar_comprobantes()
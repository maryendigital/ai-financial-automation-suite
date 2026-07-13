import os
import sys
import json
import base64
import requests
import subprocess
import shutil
import re
import tkinter as tk
from tkinter import filedialog
from dotenv import load_dotenv
from typing import Optional, Dict, Any, Union, List

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment
except ImportError:
    print("\033[91m❌ ERROR: La librería 'openpyxl' no está disponible.\033[0m")
    print("💡 Ejecuta: pip install openpyxl")
    sys.exit(1)

# ==========================================
# 1. CONSTANTES DE COLOR ANSI & ENTORNO
# ==========================================
ROJO = '\033[91m'
VERDE = '\033[92m'
AMARILLO = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'

load_dotenv("nuevo.env", override=True)

IA_API_KEY = os.getenv("IA_API_KEY")
IA_ENDPOINT = os.getenv("IA_ENDPOINT", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions")
IA_MODEL = os.getenv("IA_MODEL", "qwen-vl-plus")
IA_TIMEOUT = int(os.getenv("IA_TIMEOUT", "60"))
IA_PROVIDER = os.getenv("IA_PROVIDER", "QWEN")

if not IA_API_KEY:
    print(f"{ROJO}❌ ERROR: Configura IA_API_KEY en nuevo.env{RESET}")
    sys.exit(1)

HEADERS_IA = {
    "Authorization": f"Bearer {IA_API_KEY}",
    "Content-Type": "application/json"
}

# ==========================================
# 2. FUNCIÓN DE REPARACIÓN AVANZADA DE JSON
# ==========================================
def reparar_json_llm(txt: str) -> str:
    """
    Limpia imperfecciones de sintaxis y balancea automáticamente cierres 
    de llaves o corchetes faltantes debido a truncamientos de la API.
    """
    txt = txt.strip()
    # 1. Elimina comas huérfanas antes de cierres (trailing commas)
    txt = re.sub(r',\s*([\]}])', r'\1', txt)
    # 2. Inserta comas faltantes entre objetos correlativos
    txt = re.sub(r'}\s*{', '},{', txt)
    txt = re.sub(r'\]\s*\[', '],[', txt)
    
    # 3. ESCUDO DE AUTO-BALANCEO: Detecta y añade cierres faltantes
    llaves_abiertas = txt.count('{') - txt.count('}')
    corchetes_abiertos = txt.count('[') - txt.count(']')
    
    if corchetes_abiertos > 0:
        txt += ']' * corchetes_abiertos
    if llaves_abiertas > 0:
        txt += '}' * llaves_abiertas
        
    return txt.strip()

# ==========================================
# 3. FUNCIÓN UNIVERSAL DE LLAMADA A LA IA
# ==========================================
def llamar_ia(prompt: str, system_msg: str, imagen_base64: Optional[str] = None) -> Optional[Dict[str, Any]]:
    content = [{"type": "text", "text": prompt}]
    messages = [{"role": "system", "content": system_msg}] + [{"role": "user", "content": content}]
        
    if imagen_base64:
        if not imagen_base64.startswith("data:image"):
            imagen_base64 = f"data:image/jpeg;base64,{imagen_base64}"
        messages[-1]["content"].append({"type": "image_url", "image_url": {"url": imagen_base64}})

    payload = {
        "model": IA_MODEL,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    raw_content = ""
    try:
        resp = requests.post(IA_ENDPOINT, headers=HEADERS_IA, json=payload, timeout=IA_TIMEOUT)
        resp.raise_for_status()
        
        raw_content = resp.json()["choices"][0]["message"]["content"]
        raw_content = raw_content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        
        # Ejecutar reparación sintáctica defensiva
        json_reparado = reparar_json_llm(raw_content)
        return json.loads(json_reparado)
        
    except json.JSONDecodeError as json_err:
        print(f"{ROJO}❌ Error al decodificar JSON: {json_err}{RESET}")
        print(f"{AMARILLO}🔍 Estructura cruda recuperada de la API:{RESET}\n{raw_content}\n")
        return None
    except Exception as e:
        print(f"{AMARILLO}⚠️ Error de comunicación con la API: {e}{RESET}")
        return None

def encode_image_to_base64(path: str) -> str:
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# ==========================================
# 4. FLUJO PRINCIPAL DE PROCESAMIENTO
# ==========================================
def main():
    print(f"{CYAN}🚀 Iniciando extractor con Capa Defensiva Anti-Errores v2...{RESET}")
    
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    ruta_imagen = filedialog.askopenfilename(
        title="Selecciona la imagen de recibos de transacciones",
        filetypes=[("Imágenes", "*.jpeg *.jpg *.png *.webp")]
    )
    
    if not ruta_imagen:
        print(f"{AMARILLO}⚠️ Operación cancelada.{RESET}")
        return

    try:
        img_b64 = encode_image_to_base64(ruta_imagen)
    except Exception as e:
        print(f"{ROJO}❌ Error al leer la imagen: {e}{RESET}")
        return

    system_instruction = (
        "Eres un transcriptor de texto manuscrito de alta fidelidad. Tu única función es extraer "
        "el texto crudo de los recibos sin interpretar, clasificar o realizar limpieza de unidades. "
        "Devuelve un objeto JSON con la llave raíz 'recibos' conteniendo una lista de objetos."
    )
    
    # PROMPT DE VERIFICACIÓN ESPACIAL (Corrige las desviaciones del Día 2 y los 140 Bs)
    prompt_reglas = (
        "La imagen contiene 8 recibos organizados simétricamente en una cuadrícula de 2 columnas:\n"
        "- Columna Izquierda (arriba a abajo): Recibo 1 (Día 2), Recibo 2 (Día 9), Recibo 3 (Día 12), Recibo 4 (Día 16).\n"
        "- Columna Derecha (arriba a abajo): Recibo 5 (Día 19), Recibo 6 (Día 21), Recibo 7 (Día 23), Recibo 8 (Día 26).\n\n"
        "Transcribe secuencialmente el contenido manuscrito de cada uno respetando estrictamente estas pautas:\n"
        "1. Revisa con cuidado la esquina superior derecha de cada cuadro para extraer la 'fecha_cruda'. El primer recibo es '2/4/26', NO lo confundas con un 21.\n"
        "2. Identifica en qué línea exacta está escrito el monto a mano. Si está en la primera línea es 'Donaciones (Obra mundial)'. Si está en la segunda línea es 'Donaciones (Gastos de la congregación)'.\n"
        "   ⚠️ ATENCIÓN: En el recibo de la fecha 23/4/26 (Columna derecha, posición 3), el monto '140 Bs' está en la SEGUNDA LÍNEA, que corresponde a 'Donaciones (Gastos de la congregación)'.\n\n"
        "Devuelve la estructura exacta en este formato JSON:\n"
        "{\n"
        "  \"recibos\": [\n"
        "    {\n"
        "      \"fecha_cruda\": \"Fecha completa encontrada\",\n"
        "      \"bloques\": [\n"
        "        {\n"
        "          \"concepto_impreso\": \"Línea exacta donde se escribió el monto\",\n"
        "          \"monto_manuscrito\": \"Monto tal cual aparece con sus letras (ej: '550 Bs', '140 Bs')\"\n"
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    print(f"{CYAN}🤖 Transcribiendo texto crudo desde la imagen...{RESET}")
    data_extraida = llamar_ia(prompt=prompt_reglas, system_msg=system_instruction, imagen_base64=img_b64)

    if not data_extraida or "recibos" not in data_extraida:
        print(f"{ROJO}❌ Error: No se pudo procesar la respuesta de la IA. Inténtalo nuevamente.{RESET}")
        return

    # ==========================================
    # 5. MOTOR DE PROCESAMIENTO DETERMINISTA (PYTHON)
    # ==========================================
    transacciones_finales = []
    
    for rec in data_extraida["recibos"]:
        fecha_txt = str(rec.get("fecha_cruda", "")).strip()
        partes_fecha = fecha_txt.split("/")
        
        if partes_fecha:
            dia_str = "".join([c for c in partes_fecha[0] if c.isdigit()])
            fecha_val = int(dia_str) if dia_str else ""
        else:
            fecha_val = ""

        for b in rec.get("bloques", []):
            concepto_orig = str(b.get("concepto_impreso", "")).strip()
            monto_orig = str(b.get("monto_manuscrito", "")).strip()
            concepto_lower = concepto_orig.lower()
            
            if "obra mundial" in concepto_lower:
                ct_val = "O"
                contenido_val = "Donaciones (Obra mundial)"
            elif "congregación" in concepto_lower or "gastos" in concepto_lower:
                ct_val = "C"
                contenido_val = "Donaciones (Gastos de la congregación)"
            elif "no hubo" in concepto_lower or "contribuciones" in concepto_lower:
                ct_val = ""
                contenido_val = "No hubo Contribuciones"
            else:
                ct_val = ""
                contenido_val = concepto_orig

            # Saneamiento de cadenas numéricas (Elimina 'Bs' y caracteres basura de la cursiva)
            monto_sin_bs = re.sub(r'(?i)bs.*', '', monto_orig)
            digitos = "".join([c for c in monto_sin_bs if c.isdigit()])
            
            if len(digitos) > 2 and digitos[-2] == '0' and digitos[-1] in ['3', '5', '8']:
                digitos = digitos[:-1]
                
            try:
                subtotal_val = int(digitos) if digitos else 0
            except:
                subtotal_val = 0
                
            if "no hubo" in concepto_lower:
                subtotal_val = 0
                ct_val = ""

            if subtotal_val == 0 and "no hubo" not in concepto_lower:
                continue

            transacciones_finales.append({
                "FECHA": fecha_val,
                "CONTENIDO": contenido_val,
                "CT": ct_val,
                "SUBTOTAL": subtotal_val,
                "TIPO": "Donación"
            })

    # Ordenamiento cronológico garantizado por Python
    transacciones_finales.sort(key=lambda x: int(x["FECHA"]) if str(x["FECHA"]).isdigit() else 999)

    # ==========================================
    # 6. GENERACIÓN DE ARCHIVO DE SALIDA (.XLSX)
    # ==========================================
    ruta_temporal = os.path.join(os.getcwd(), "temp_viewer.xlsx")
    
    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Borrador Transacciones"
        
        headers = ["FECHA", "CONTENIDO", "CT", "SUBTOTAL", "TIPO"]
        ws.append(headers)
        
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = Font(bold=True, name="Arial")
            cell.alignment = Alignment(horizontal="center")
            
        for item in transacciones_finales:
            fila = [item["FECHA"], item["CONTENIDO"], item["CT"], item["SUBTOTAL"], item["TIPO"]]
            ws.append(fila)
            
        wb.save(ruta_temporal)
        print(f"{VERDE}✅ Borrador estructurado y ordenado cronológicamente con éxito.{RESET}")
        
        print(f"{CYAN}👁️  Abriendo visualizador en VS Code...{RESET}")
        subprocess.Popen(['code', ruta_temporal], shell=True)
        
    except Exception as e:
        print(f"{ROJO}❌ Error al construir el Excel: {e}{RESET}")
        return

    print(f"\n{CYAN}=================================================={RESET}")
    decision = input("¿Deseas conservar y guardar este reporte verificado? (s/n): ").strip().lower()
    
    if decision == 's':
        nombre_final = input("Introduce el nombre definitivo del archivo Excel: ").strip()
        if not nombre_final.lower().endswith(".xlsx"):
            nombre_final += ".xlsx"
            
        ruta_final = os.path.join(os.getcwd(), nombre_final)
        try:
            shutil.copy2(ruta_temporal, ruta_final)
            print(f"{VERDE}✨ ¡Archivo definitivo consolidado con éxito en: {ruta_final}!{RESET}")
        except Exception as e:
            print(f"{ROJO}❌ Error al salvar el archivo permanente: {e}{RESET}")
    else:
        print(f"{AMARILLO}🚫 Datos descartados por el usuario.{RESET}")

    try:
        if os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)
            print(f"{VERDE}🧹 Limpieza de temporales finalizada.{RESET}")
    except PermissionError:
        print(f"{AMARILLO}⚠️  Aviso: Cierra la pestaña en VS Code para liberar los permisos de edición del temporal.{RESET}")

if __name__ == "__main__":
    main()
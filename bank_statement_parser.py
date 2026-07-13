import os
import io
import re
import json
import base64
import requests
import pandas as pd
import tkinter as tk
from tkinter import filedialog
from dotenv import load_dotenv
import pypdfium2 as pdfium

def inicializar_entorno():
    """Carga las variables desde accesoimagen.env usando dotenv."""
    load_dotenv("accesoimagen.env", override=True)
    return os.getenv("NVIDIA_API_KEY")

def limpiar_numero(valor):
    """Detecta y limpia inteligentemente formatos como 4.000,00 o 1,200.00 a decimal puro."""
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        s = str(valor).replace("Bs.", "").replace(" ", "").strip()
        if not s: return 0.0
        
        is_negative = '-' in s
        s = s.replace('-', '')
        
        # Busca todos los puntos y comas en el número
        separadores = re.findall(r'[.,]', s)
        if separadores:
            # El último símbolo encontrado siempre será el decimal
            ultimo_sep = s.rfind(separadores[-1])
            parte_entera = s[:ultimo_sep].replace('.', '').replace(',', '')
            parte_decimal = s[ultimo_sep+1:]
            s = f"{parte_entera}.{parte_decimal}"
        
        try:
            val = float(s)
            return -val if is_negative else val
        except ValueError:
            return 0.0
    return 0.0

def pdf_a_base64_imagenes(ruta_pdf):
    """Convierte todas las páginas del PDF en imágenes Base64 utilizando pypdfium2."""
    imagenes_base64 = []
    doc = pdfium.PdfDocument(ruta_pdf)
    
    for i in range(len(doc)):
        pagina = doc[i]
        bitmap = pagina.render(scale=2)
        pil_img = bitmap.to_pil()
        
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG")
        img_bytes = buffer.getvalue()
        
        base64_encoded = base64.b64encode(img_bytes).decode("utf-8")
        imagenes_base64.append(f"data:image/png;base64,{base64_encoded}")
        
    return imagenes_base64

def extraer_datos_pagina_nvidia(img_url, num_pagina, api_key):
    """Envía una ÚNICA página a NVIDIA con aislamiento radical de JSON."""
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    prompt = """
    Eres un procesador de datos bancarios. Analiza la imagen de esta página de estado de cuenta.
    Extrae TODAS las filas de transacciones de la tabla principal.
    
    REGLA DE ORO: TU RESPUESTA DEBE EMPEZAR EXACTAMENTE CON EL SÍMBOLO '[' Y TERMINAR CON ']'. 
    ESTÁ ESTRICTAMENTE PROHIBIDO incluir saludos, explicaciones, o texto conversacional antes o después del arreglo JSON.
    Si la página no contiene transacciones bancarias, responde ÚNICAMENTE con: []
    
    REGLAS DE SINTAXIS JSON:
    1. Separa cada objeto con una coma (,).
    2. NUNCA uses comillas dobles (") dentro del texto del 'concepto'. Reemplázalas por comillas simples (').
    
    Cada objeto debe tener estas claves:
    - "fecha": (Formato DD-MM-YYYY).
    - "concepto": (Descripción completa de la transacción).
    - "monto": (Float. Cargos negativos, abonos positivos. Ej: -3750.00).
    - "saldo": (Float. Saldo final de la fila).
    """
    
    content_payload = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": img_url}}
    ]
        
    payload = {
        "model": "meta/llama-3.2-11b-vision-instruct",
        "messages": [{"role": "user", "content": content_payload}],
        "max_tokens": 4096,
        "temperature": 0.1
    }
    
    print(f"      Analizando estructura visual de la página {num_pagina}...")
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200:
        raise Exception(f"Error en la API de NVIDIA ({response.status_code}): {response.text}")
        
    texto_respuesta = response.json()["choices"][0]["message"]["content"].strip()
    
    # 1. AISLAMIENTO RADICAL: Buscar solo el bloque desde '[' hasta ']'
    idx_inicio = texto_respuesta.find('[')
    idx_fin = texto_respuesta.rfind(']')
    
    if idx_inicio != -1 and idx_fin != -1 and idx_fin > idx_inicio:
        texto_limpio = texto_respuesta[idx_inicio:idx_fin+1]
    else:
        # Si no encontró corchetes, la IA se negó a procesarlo (Posible filtro de seguridad)
        texto_limpio = texto_respuesta
    
    # 2. Limpieza de saltos de línea para el parser
    texto_limpio = texto_limpio.replace('\n', ' ').replace('\r', '')
    texto_limpio = re.sub(r'\}\s*\{', '}, {', texto_limpio) # Repara comas faltantes entre objetos
    texto_limpio = re.sub(r',\s*\]', ']', texto_limpio) # Repara comas sobrantes al final
    
    try:
        # Intento de parseo nativo
        return json.loads(texto_limpio)
    except json.JSONDecodeError as e:
        print(f"\n      [Advertencia] Error de sintaxis en el formato de la IA.")
        
        # 3. PROTOCOLO DE RESCATE EXTREMO
        datos_recuperados = []
        bloques_objetos = re.findall(r'\{[^{}]+\}', texto_limpio)
        
        if not bloques_objetos:
            print(f"      -> [CRÍTICO] La IA no devolvió ningún dato válido. Su respuesta fue:\n         '{texto_respuesta[:200]}...'")
            return []
            
        for bloque in bloques_objetos:
            try:
                datos_recuperados.append(json.loads(bloque))
            except json.JSONDecodeError:
                try:
                    fecha_m = re.search(r'"fecha"\s*:\s*"([^"]+)"', bloque)
                    fecha = fecha_m.group(1) if fecha_m else ""
                    
                    monto_m = re.search(r'"monto"\s*:\s*"?(-?[\d.]+)"?', bloque)
                    monto = float(monto_m.group(1)) if monto_m else 0.0
                    
                    saldo_m = re.search(r'"saldo"\s*:\s*"?(-?[\d.]+)"?', bloque)
                    saldo = float(saldo_m.group(1)) if saldo_m else 0.0
                    
                    concepto_m = re.search(r'"concepto"\s*:\s*"(.*?)"\s*,\s*"monto"', bloque)
                    concepto = concepto_m.group(1) if concepto_m else "Transacción recuperada"
                    concepto = concepto.replace('"', '').replace('\\', '').strip()
                    
                    if fecha:
                        datos_recuperados.append({
                            "fecha": fecha,
                            "concepto": concepto,
                            "monto": monto,
                            "saldo": saldo
                        })
                except Exception:
                    pass
                    
        return datos_recuperados

def procesar_estado_cuenta():
    api_key = inicializar_entorno()
    if not api_key:
        print("Error: No se pudo obtener la variable NVIDIA_API_KEY desde 'accesoimagen.env'.")
        return

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    ruta_pdf = filedialog.askopenfilename(
        title="Selecciona el PDF de movimientos (PROV MARZO GM)",
        filetypes=[("Archivos PDF", "*.pdf")]
    )

    if not ruta_pdf:
        print("No seleccionaste ningún archivo. Proceso cancelado.")
        return

    try:
        print(f"\n[1/4] Conectando con la Inteligencia Artificial de NVIDIA...")
        print("      Procesando páginas del documento PDF en memoria local...")
        imagenes = pdf_a_base64_imagenes(ruta_pdf)
        
        datos = []
        for indice, img_b64 in enumerate(imagenes, start=1):
            datos_pagina = extraer_datos_pagina_nvidia(img_b64, indice, api_key)
            if datos_pagina and isinstance(datos_pagina, list):
                datos.extend(datos_pagina)
                
        if not datos:
            print("\n❌ Error fatal: No se pudo recuperar información estructurada de ninguna página.")
            print("   (Es probable que la IA haya bloqueado el documento por filtros de privacidad/seguridad o no pudo leer la imagen).")
            return
        
        # 1. Asegurar el orden cronológico
        try:
            def obtener_clave_fecha(x):
                partes = re.split(r'[/-]', x['fecha'])
                return int(partes[2])*10000 + int(partes[1])*100 + int(partes[0])
            
            if len(datos) > 1 and obtener_clave_fecha(datos[0]) > obtener_clave_fecha(datos[-1]):
                datos.reverse()
        except Exception:
            datos.reverse()
        
        # --- NUEVO: Forzar limpieza numérica absoluta en todos los datos recuperados ---
        for mov in datos:
            mov['monto'] = limpiar_numero(mov.get('monto', 0))
            mov['saldo'] = limpiar_numero(mov.get('saldo', 0))
        
        # 2. Reconstrucción matemática de los saldos iniciales
        primer_mov = datos[0]
        saldo_anterior = primer_mov['saldo'] - primer_mov['monto']
        saldo_final = datos[-1]['saldo']
        
        # 3. Estructurar líneas para el bloc de notas
        lineas_texto = [
            "DETALLE DE MOVIMIENTOS Situación al: 31-03-2026\n",
            "F. OPER. REF. CONCEPTO F. VALOR CARGOS ABONOS SALDO",
            f"SALDO ANTERIOR {saldo_anterior:,.2f}"
        ]
        
        # 4. Preparar DataFrame para Excel Viewer
        filas_previsualizacion = [{
            'F. OPER.': 'SALDO ANTERIOR', 'REF.': '', 'CONCEPTO': '', 
            'F. VALOR': '', 'MONTO': '', 'SALDO': f"{saldo_anterior:,.2f}"
        }]
        
        for i, mov in enumerate(datos, start=1):
            ref = f"{i:03d}"
            # Se fuerza a que todas las fechas salgan con guiones
            fecha = mov['fecha'].replace('/', '-')
            concepto = mov['concepto']
            monto_fmt = f"{abs(mov['monto']):,.2f}"
            saldo_fmt = f"{mov['saldo']:,.2f}"
            
            lineas_texto.append(f"{fecha} {ref} {concepto} {fecha} {monto_fmt} {saldo_fmt}")
            
            filas_previsualizacion.append({
                'F. OPER.': fecha, 'REF.': ref, 'CONCEPTO': concepto, 
                'F. VALOR': fecha, 'MONTO': monto_fmt, 'SALDO': saldo_fmt
            })
            
        lineas_texto.append("Saldo a nuestro favor Saldo a su favor")
        lineas_texto.append(f"{saldo_final:,.2f}")
        
        filas_previsualizacion.append({
            'F. OPER.': 'Saldo a nuestro favor Saldo a su favor', 'REF.': '', 'CONCEPTO': '', 
            'F. VALOR': '', 'MONTO': '', 'SALDO': f"{saldo_final:,.2f}"
        })
        
        # 5. Generar vista previa temporal
        df_preview = pd.DataFrame(filas_previsualizacion)
        nombre_temporal = "PREVISUALIZACION_TEMPORAL.xlsx"
        df_preview.to_excel(nombre_temporal, index=False, engine='openpyxl')
        
        print(f"\n[2/4] [VISTA PREVIA CREADA]: '{nombre_temporal}'")
        print("👉 Abre la barra lateral de VS Code y revisa los datos con tu extensión Excel Viewer.")
        
        # Confirmación de guardado
        confirmacion = input("\n¿Deseas descargar el archivo en formato de texto plano (.txt)? (s/n): ").strip().lower()
        
        if confirmacion == 's':
            nombre_final = input("Escribe el nombre para tu archivo final (sin .txt): ").strip()
            if not nombre_final: 
                nombre_final = "EstadoDeCuenta_Procesado_NVIDIA"
                
            ruta_txt_salida = os.path.join(os.path.dirname(ruta_pdf), f"{nombre_final}.txt")
            
            with open(ruta_txt_salida, "w", encoding="utf-8") as f:
                f.write("\n".join(lineas_texto))
                
            print(f"\n[3/4] ¡Guardado Exitoso! Texto limpio generado en:\n--> {ruta_txt_salida}")
        else:
            print("\n[3/4] Operación de descarga omitida.")
            
        # 6. Limpieza
        input("\n[4/4] Presiona la tecla ENTER en esta terminal para borrar el archivo temporal y finalizar...")
        
        if os.path.exists(nombre_temporal):
            try:
                os.remove(nombre_temporal)
                print("Archivo temporal eliminado correctamente.")
            except Exception:
                pass
                
    except Exception as e:
        print(f"Error en el motor de procesamiento: {e}")

if __name__ == "__main__":
    procesar_estado_cuenta()
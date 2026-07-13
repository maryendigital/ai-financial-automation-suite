#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validador Universal de API IA - Estándar Mínimo (Solo IA_API_KEY)
Si falla, muestra sugerencias específicas para corregir la conexión.
"""
import os
import sys
import time
import json
import requests
from dotenv import load_dotenv

# Colores ANSI
ROJO = '\033[91m'
VERDE = '\033[92m'
AMARILLO = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'

def print_sugerencia(msg: str):
    print(f"  {AMARILLO}💡 {msg}{RESET}")

def validar_api_universal() -> bool:
    print(f"\n{CYAN}🔍 VALIDADOR API IA (ESTÁNDAR MÍNIMO){RESET}")
    print("=" * 50)

    # 1. Cargar nuevo.env
    print("  📁 Buscando nuevo.env...")
    if not os.path.exists("nuevo.env"):
        print(f"  {ROJO}❌ No se encontró 'nuevo.env' en el directorio actual{RESET}")
        print_sugerencia("Crea un archivo llamado 'nuevo.env' con:")
        print_sugerencia("  IA_API_KEY=sk-tu_clave_aqui")
        print_sugerencia("Guárdalo en la misma carpeta donde ejecutas este script.")
        return False
    
    load_dotenv("nuevo.env", override=True)
    
    # 2. Extraer variables con defaults
    api_key = os.getenv("IA_API_KEY")
    endpoint = os.getenv("IA_ENDPOINT", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions")
    model = os.getenv("IA_MODEL", "qwen-plus")
    provider = os.getenv("IA_PROVIDER", "QWEN")
    timeout = int(os.getenv("IA_TIMEOUT", "60"))
    
    # 3. Validaciones con sugerencias específicas
    if not api_key:
        print(f"  {ROJO}❌ Falta IA_API_KEY en nuevo.env{RESET}")
        print_sugerencia("Añade esta línea a nuevo.env:")
        print_sugerencia(f"  IA_API_KEY=tu_clave_secreta")
        print_sugerencia("Obtén tu clave en: https://dashscope.console.aliyun.com/apiKey")
        return False
    
    print(f"  {VERDE}✅ Proveedor: {provider} (por defecto){RESET}")
    print(f"  {VERDE}✅ Modelo: {model} (por defecto){RESET}")
    print(f"  {VERDE}✅ Clave: {api_key[:6]}...{api_key[-4:]}{RESET}")
    print(f"  {CYAN}🌐 Endpoint: {endpoint}{RESET}")

    # 4. Preparar request de prueba
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Responde SOLO con un JSON válido."},
            {"role": "user", "content": "Genera: {'status': 'ok', 'modelo': 'nombre', 'timestamp': 'fecha'}"}
        ],
        "max_tokens": 100,
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }

    # 5. Ejecutar llamada
    print(f"  📡 Conectando (timeout: {timeout}s)...")
    start_time = time.time()
    
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        latency = time.time() - start_time
        
        # Verificar status code con sugerencias
        if response.status_code == 401:
            print(f"  {ROJO}❌ Error 401: Clave API inválida o expirada{RESET}")
            print_sugerencia("Verifica que IA_API_KEY en nuevo.env sea correcta")
            print_sugerencia("Renueva tu clave en la consola del proveedor si es necesario")
            return False
        elif response.status_code == 404:
            print(f"  {ROJO}❌ Error 404: Endpoint no encontrado{RESET}")
            print_sugerencia("Verifica que IA_ENDPOINT sea correcto para tu proveedor")
            print_sugerencia("Ejemplo Qwen: https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions")
            return False
        elif response.status_code == 429:
            print(f"  {ROJO}❌ Error 429: Límite de peticiones excedido{RESET}")
            print_sugerencia("Espera unos segundos o revisa tu plan de uso en la consola")
            return False
        elif response.status_code != 200:
            print(f"  {ROJO}❌ Error HTTP {response.status_code}{RESET}")
            print(f"  {ROJO}Respuesta: {response.text[:200]}{RESET}")
            print_sugerencia("Revisa tu conexión, clave API o configuración del endpoint")
            return False
        
        # Parsear respuesta
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # Validar JSON
        try:
            json_resp = json.loads(content)
            print(f"  {VERDE}✅ JSON válido recibido{RESET}")
        except json.JSONDecodeError:
            print(f"  {AMARILLO}⚠️ La IA no devolvió JSON válido{RESET}")
            print(f"  {AMARILLO}Respuesta raw: {content[:100]}...{RESET}")
            print_sugerencia("Intenta con otro modelo o revisa el prompt del sistema")
        
        # Métricas
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", "N/A")
        print(f"  {CYAN}⏱️ Latencia: {latency:.2f}s | Tokens: {tokens}{RESET}")
        
        # Éxito
        print(f"\n{VERDE}{'='*50}{RESET}")
        print(f"  {VERDE}🏁 API OPERATIVA. LISTA PARA INTEGRAR.{RESET}")
        print(f"{VERDE}{'='*50}{RESET}\n")
        return True

    except requests.exceptions.Timeout:
        print(f"  {ROJO}❌ Timeout: La API no respondió en {timeout}s{RESET}")
        print_sugerencia("Verifica tu conexión a internet")
        print_sugerencia("Aumenta IA_TIMEOUT en nuevo.env si tu red es lenta")
        print_sugerencia("Prueba con un endpoint más cercano geográficamente")
        return False
    except requests.exceptions.ConnectionError:
        print(f"  {ROJO}❌ Error de conexión: No se pudo alcanzar el endpoint{RESET}")
        print_sugerencia("Verifica que IA_ENDPOINT sea accesible desde tu red")
        print_sugerencia("Si usas proxy, configura las variables HTTP_PROXY/HTTPS_PROXY")
        print_sugerencia("Prueba hacer ping al dominio del endpoint")
        return False
    except requests.exceptions.SSLError:
        print(f"  {ROJO}❌ Error SSL: Problema con el certificado HTTPS{RESET}")
        print_sugerencia("Verifica la fecha/hora de tu sistema")
        print_sugerencia("Actualiza tus certificados CA o usa requests con verify=False (no recomendado en producción)")
        return False
    except Exception as e:
        print(f"  {ROJO}❌ Error inesperado: {type(e).__name__} - {e}{RESET}")
        print_sugerencia("Revisa la documentación del proveedor o contacta soporte")
        return False

if __name__ == "__main__":
    success = validar_api_universal()
    sys.exit(0 if success else 1)
import os
import json  # Para trabajar con el archivo JSON
import asyncio
import time
from datetime import datetime
import tkinter as tk
from tkinter import filedialog
from playwright.async_api import async_playwright
import re
from twocaptcha import TwoCaptcha  # Importa la librería 2Captcha

# Cargar configuración desde el archivo JSON
def load_config(file_name="config.json"):
    """Leer el archivo config.json para cargar la configuración."""
    if os.path.exists(file_name):
        with open(file_name, 'r') as config_file:
            config = json.load(config_file)
            # Validación básica de la configuración
            if "clientKey" in config and "task" in config and "websiteURL" in config["task"] and "websiteKey" in config["task"]:
                return config
            else:
                raise ValueError("La configuración no contiene todos los campos necesarios.")
    else:
        raise FileNotFoundError(f"No se encontró el archivo {file_name}")

def select_file():
    """Abrir el explorador de archivos para seleccionar un archivo .txt"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Seleccione un archivo de texto",
        filetypes=[("Archivos de texto", "*.txt")]
    )
    return file_path

def load_proxies(file_name="proxies.txt"):
    """Leer el archivo proxies.txt y devolver una lista de proxies"""
    proxies = []
    if os.path.exists(file_name):
        with open(file_name, 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
    return proxies

def extract_email_from_line(line):
    """Extrae solo el correo electrónico de una línea que puede contener también la contraseña"""
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', line)
    if match:
        return match.group(0)
    return None

async def solve_hcaptcha_with_2captcha(config, proxy=None):
    """Resolver HCaptcha utilizando 2Captcha con soporte para proxies"""
    solver = TwoCaptcha(config["clientKey"])
    try:
        task_params = {
            "sitekey": config["task"]["websiteKey"],
            "url": config["task"]["websiteURL"]
        }
        if proxy:
            task_params.update({
                "proxyType": 'http',
                "proxyAddress": proxy['ip'],
                "proxyPort": proxy['port']
            })
        result = solver.hcaptcha(**task_params)
        
        # Imprimir el resultado para verificar la respuesta del captcha
        print(f"Resultado de 2Captcha: {result}")

        if "code" in result:
            return result["code"]
        else:
            print("No se encontró el código de resolución en la respuesta de 2Captcha.")
            return None
    except Exception as e:
        print(f"Error al resolver HCaptcha: {str(e)}")
        return None

async def main():
    try:
        # Cargar la configuración desde el archivo config.json
        config = load_config()

        # Abrir el explorador de archivos para seleccionar un archivo .txt
        file_path = select_file()

        if not file_path:
            print('No se ha seleccionado un archivo. Saliendo...')
            return

        # Verifica si el archivo existe
        if not os.path.exists(file_path):
            print('El archivo no existe. Asegúrate de seleccionar una ruta válida.')
            return

        # Lee los correos electrónicos desde el archivo
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
            emails = [extract_email_from_line(line) for line in lines]
            emails = [email for email in emails if email]  # Filtrar correos no válidos

        # Carga las proxies desde el archivo proxies.txt
        proxies = load_proxies()

        # Crea la carpeta de resultados con timestamp
        now = datetime.now()
        result_dir = f"./results/results_{now.hour}-{now.minute}-{now.second}_{now.day}-{now.month}-{now.year}"
        os.makedirs(result_dir, exist_ok=True)
        registered_path = os.path.join(result_dir, 'registered.txt')
        unregistered_path = os.path.join(result_dir, 'unregistered.txt')

        # Inicia Playwright y ejecuta el proceso
        async with async_playwright() as p:
            for i, email in enumerate(emails):
                print(f"Procesando {email}...")

                # Verifica si hay proxies disponibles antes de intentar usarlas
                proxy = None
                if proxies:
                    proxy_info = proxies[i % len(proxies)].split(':')
                    proxy = {
                        'ip': proxy_info[0],
                        'port': proxy_info[1]
                    }
                    print(f"Usando proxy: {proxy['ip']}:{proxy['port']}")
                else:
                    print("Sin proxy para este correo.")

                # Inicia el navegador con o sin proxy dependiendo de si hay proxies
                if proxy:
                    browser = await p.chromium.launch(
                        headless=False,
                        proxy={
                            "server": f"http://{proxy['ip']}:{proxy['port']}"
                        }
                    )
                else:
                    browser = await p.chromium.launch(headless=False)

                page = await browser.new_page()

                # Navega a la página de recuperación de contraseña
                await page.goto(config["task"]["websiteURL"], wait_until='networkidle')

                # Espera explícitamente a que el campo de correo esté disponible
                await page.wait_for_selector('#email')

                # Limpia el campo de correo y escribe solo el correo
                await page.fill('#email', email)

                # Espera explícitamente a que el selector '#send > span' esté disponible
                print("Esperando a que cargue el botón de enviar.")
                await page.wait_for_selector('#send > span')

                # Hacer clic en el botón de enviar
                await page.click('#send > span')
                print("Email enviado, esperando que cargue el captcha...")

                # Espera a que aparezca el captcha (selector body > div)
                print("Esperando a que aparezca el captcha.")
                await page.wait_for_selector('body > div > div.challenge-container > div > div > canvas', timeout=60000)
                print("Captcha detectado, resolviendo...")

                # Resolver HCaptcha utilizando 2Captcha (con proxy o sin proxy)
                captcha_solution = await solve_hcaptcha_with_2captcha(config, proxy=proxy)

                if captcha_solution:
                    # Aplicar la solución del Captcha
                    print("Aplicando la solución del captcha.")
                    await page.evaluate(f'document.getElementById("h-captcha-response").value = "{captcha_solution}";')

                    # Haz clic en el botón "Continuar"
                    await page.click('span.EuiButton-innerLabel')

                    # Espera una respuesta y verifica los resultados
                    try:
                        success_msg = await page.wait_for_selector('h4.MuiTypography-root.MuiTypography-h4', timeout=15000)
                        if success_msg:
                            print(f"El correo {email} está registrado.")
                            with open(registered_path, 'a', encoding='utf-8') as f:
                                f.write(f"{email}\n")
                        else:
                            raise Exception("Success message not found")
                    except Exception as e:
                        error_msg = await page.query_selector('p.MuiTypography-root.MuiTypography-body2')
                        if error_msg:
                            print(f"El correo {email} no está registrado.")
                            with open(unregistered_path, 'a', encoding='utf-8') as f:
                                f.write(f"{email}\n")
                        else:
                            print(f"No se pudo determinar el estado de {email}.")
                else:
                    print(f"Error al resolver el captcha para {email}")

                await asyncio.sleep(5)

                # Cerrar el navegador antes de procesar el siguiente correo
                await browser.close()

    except Exception as e:
        print(f'Error en la ejecución de Playwright: {str(e)}')

# Ejecuta el bucle principal de asyncio para lanzar Playwright
asyncio.run(main())

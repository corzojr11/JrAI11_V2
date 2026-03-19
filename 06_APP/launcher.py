import subprocess
import sys
import os

if __name__ == "__main__":
    base_path = os.path.dirname(os.path.abspath(__file__))
    # El intérprete de Python está en la carpeta _internal
    python_exe = os.path.join(base_path, "_internal", "python.exe")
    # Por si acaso, verificamos que exista
    if not os.path.exists(python_exe):
        # Fallback: usar sys.executable (aunque no funcionará)
        python_exe = sys.executable
        print("No se encontró python.exe en _internal, usando sys.executable")
    
    app_path = os.path.join(base_path, "app.py")
    print("Python:", python_exe)
    print("App:", app_path)
    print("Archivos en base:", os.listdir(base_path))
    
    if not os.path.exists(app_path):
        print("Error: No se encuentra app.py")
        input("Presiona Enter...")
        sys.exit(1)
    
    cmd = [python_exe, "-m", "streamlit", "run", app_path]
    print("Ejecutando:", " ".join(cmd))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        print("Código de retorno:", result.returncode)
        if result.stdout:
            print("STDOUT:", result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
    except Exception as e:
        print("Excepción:", e)
    
    input("Presiona Enter para salir...")
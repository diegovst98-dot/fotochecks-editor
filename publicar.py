"""
Publicar una actualizacion del Editor de Fotos - DISECOD.

Que hace, en orden:
  1) Sube el numero de version (+1).
  2) Arma el manifest.json (version + lista de archivos de codigo/).
  3) Sube los cambios a GitHub.

Despues de esto, cada PC que abra el programa descargara la actualizacion sola.
NO hace falta reenviar el .exe ni el ZIP: solo se actualiza la carpeta codigo/
(pocos KB). El .exe solo se vuelve a repartir si cambian las librerias o el
modelo de IA (cosa rara).

Uso: doble clic en "publicar.bat"  (o:  python publicar.py)
"""

import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
CODIGO = BASE / "codigo"
VERSION_FILE = CODIGO / "version.txt"
MANIFEST = BASE / "manifest.json"


def _entero(texto):
    m = re.search(r"\d+", str(texto))
    return int(m.group()) if m else 0


def main():
    if not VERSION_FILE.exists():
        print("No se encontro codigo/version.txt"); return

    # CANDADO DE CALIDAD: si los tests fallan, NO se publica nada. Evita mandar
    # a las PCs del equipo un cambio que rompe algo que ya funcionaba.
    tests = BASE / "tests" / "correr_tests.py"
    if tests.exists():
        print("Corriendo tests antes de publicar (~1 min)...")
        r = subprocess.run([sys.executable, str(tests)], cwd=BASE)
        if r.returncode != 0:
            print("\n[X] LOS TESTS FALLARON - PUBLICACION CANCELADA. Nada se subio.")
            print("    Si el cambio es INTENCIONAL y ya revisaste las salidas a ojo:")
            print("    python tests\\correr_tests.py --aprobar   (y publica de nuevo)")
            return
        print("Tests OK.\n")

    actual = _entero(VERSION_FILE.read_text(encoding="utf-8"))
    nueva = actual + 1

    # 1) subir version
    VERSION_FILE.write_text(str(nueva), encoding="utf-8")

    # 2) armar manifest con TODOS los archivos de codigo/ (asi agregar un archivo
    #    nuevo de codigo se publica solo, sin tocar nada mas)
    archivos = sorted(p.name for p in CODIGO.iterdir()
                      if p.is_file() and p.suffix in (".py", ".txt"))
    manifest = {"version": nueva, "archivos": archivos}
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print("Publicando version %s ..." % nueva)
    print("Archivos:", ", ".join(archivos))

    # 3) subir a GitHub
    try:
        subprocess.run(["git", "add", "codigo", "manifest.json"], cwd=BASE, check=True)
        subprocess.run(["git", "commit", "-m", "Actualizacion version %s" % nueva],
                       cwd=BASE, check=True)
        subprocess.run(["git", "push"], cwd=BASE, check=True)
    except subprocess.CalledProcessError as e:
        print("\n[!] Error al subir a GitHub:", e)
        print("    Revisa la conexion a internet y vuelve a intentar.")
        return

    print("\nLISTO: version %s publicada." % nueva)
    print("Las PCs se actualizaran solas al abrir el programa.")


if __name__ == "__main__":
    main()

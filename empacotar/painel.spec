# PyInstaller: gera o app do Painel Financeiro.
#   Mac:     dist/Painel Financeiro.app
#   Windows: dist/Painel Financeiro/Painel Financeiro.exe  (o instalador é feito depois pelo Inno Setup)
# Rodar da raiz do projeto:  pyinstaller --noconfirm empacotar/painel.spec
# Tem que rodar em cada sistema (o PyInstaller não gera .exe no Mac nem .app no Windows).
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent
NAME = "Painel Financeiro"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "financas" / "__init__.py").read_text()).group(1)

# O Streamlit roda financas/ui/app.py como script: o código-fonte precisa ir junto (não só compilado).
datas = [(str(ROOT / "financas"), "financas"), (str(ROOT / "rules.yaml"), ".")]
# todos os módulos do projeto, para o PyInstaller achar as bibliotecas que eles usam (ofxparse, pdfplumber…)
binaries, hiddenimports = [], [
    ".".join(p.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__")
    for p in (ROOT / "financas").rglob("*.py")]
for pkg in ("streamlit", "plotly", "pdfplumber", "pdfminer"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
for pkg in ("streamlit", "plotly", "pandas", "pdfplumber", "ofxparse"):
    datas += copy_metadata(pkg)

a = Analysis(
    [str(ROOT / "painel_desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts,
    # modo UTF-8: no Windows o padrão seria cp1252 e arquivos com acento (tema, .env) quebrariam
    [("X utf8_mode=1", None, "OPTION")],
    exclude_binaries=True,
    name=NAME,
    console=False,  # sem janela preta
    icon=str(ROOT / "empacotar" / ("icone.ico" if sys.platform == "win32" else "icone.icns")),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=str(ROOT / "empacotar" / "icone.icns"),
        bundle_identifier="io.github.gabrielsaalvarenga.painelfinanceiro",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "Licença MIT",
        },
    )

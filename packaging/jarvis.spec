# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
PROJECT_ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(PROJECT_ROOT / "assets" / "images"), "assets/images"),
    (str(PROJECT_ROOT / "assets" / "everything"), "assets/everything"),
    (str(PROJECT_ROOT / "data" / "documents"), "data/documents"),
    (str(PROJECT_ROOT / "data" / "vectordb"), "data/vectordb"),
    (str(PROJECT_ROOT / "data" / "model_cache"), "data/model_cache"),
]

hiddenimports = [
    "sentence_transformers",
    "sentence_transformers.models",
    "sentence_transformers.losses",
    "sentence_transformers.cross_encoder",
    "sentence_transformers.backend",
    "chromadb",
    "chromadb.api",
    "chromadb.api.models",
    "chromadb.db",
    "chromadb.db.impl",
    "chromadb.segment",
    "chromadb.segment.impl",
    "markdown2",
    "pygments",
    "pygments.formatters",
    "pygments.lexers",
    "ddgs",
    "ddgs.engines",
    "primp",
    "requests",
    "yfinance",
    "pandas",
    "email",
    "email.mime",
    "email.mime.text",
    "email.mime.multipart",
    "onnxruntime",
    "torch",
    "torch.nn",
    "torch.nn.functional",
    "torch.distributed.tensor",
    "transformers",
    "transformers.models",
    "sympy",
    "mpmath",
    "docx",
    "pptx",
    "pdfplumber",
    "chromadb.segment.impl.distributed",
    "chromadb.segment.impl.manager",
] + collect_submodules("ddgs.engines")


a = Analysis(
    [str(PROJECT_ROOT / "scripts" / "jarvis.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / "packaging" / "hook_torch.py")],
    excludes=[
        "matplotlib",
        "tkinter",
        "torchvision",
        "torchaudio",
        "onnx.reference",
        "onnx.reference.ops",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="jarvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(PROJECT_ROOT / "assets" / "images" / "pngegg.png"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="jarvis",
)



# hook_torch.py - torch DLL 경로를 실행 전에 강제 등록
import os
import sys
import ctypes
import glob

# PyInstaller _internal 폴더 경로
internal = sys._MEIPASS
torch_lib = os.path.join(internal, 'torch', 'lib')

# 1. add_dll_directory로 등록
if hasattr(os, 'add_dll_directory'):
    for p in [torch_lib, internal]:
        if os.path.isdir(p):
            os.add_dll_directory(p)

# 2. PATH 앞에 추가
os.environ['PATH'] = torch_lib + os.pathsep + internal + os.pathsep + os.environ.get('PATH', '')

# 3. VC 런타임 먼저 강제 로드 (순서 중요)
for dll in ['vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll']:
    for base in [internal, torch_lib, r'C:\Windows\System32']:
        full = os.path.join(base, dll)
        if os.path.exists(full):
            try:
                ctypes.CDLL(full)
                break
            except Exception:
                pass

# 4. torch/lib/*.dll 전부 미리 강제 로드
if os.path.isdir(torch_lib):
    for dll in sorted(glob.glob(os.path.join(torch_lib, '*.dll'))):
        try:
            ctypes.CDLL(dll)
        except Exception:
            pass
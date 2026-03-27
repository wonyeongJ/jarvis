@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "SPEC_PATH=%PROJECT_ROOT%\packaging\jarvis.spec"
set "DIST_DIR=%PROJECT_ROOT%\dist"
set "DIST_APP_DIR=%DIST_DIR%\jarvis"
set "BUILD_DIR=%PROJECT_ROOT%\build"
set "ZIP_PATH=%PROJECT_ROOT%\jarvis_package.zip"
set "EXE_PATH=%DIST_APP_DIR%\jarvis.exe"

pushd "%PROJECT_ROOT%"

echo ===============================
echo   Jarvis Full Build Start
echo ===============================

echo.
echo [0/6] Activate venv...
call "%PROJECT_ROOT%\venv\Scripts\activate.bat"
if errorlevel 1 goto :fail_venv

echo.
echo [1/6] Stop running processes...
taskkill /f /im jarvis.exe >nul 2>nul
taskkill /f /im Everything.exe >nul 2>nul
timeout /t 2 /nobreak >nul

echo.
echo [2/6] Clean output folders...
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%DIST_DIR%" goto :fail_dist_locked
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"
if exist "%ZIP_PATH%" goto :fail_zip_locked

echo.
echo [3/6] Check build dependencies...
python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    if errorlevel 1 goto :fail_pyinstaller
) else (
    echo PyInstaller already installed.
)

python -c "import primp" >nul 2>nul
if errorlevel 1 (
    echo primp not found. Installing...
    pip install primp
    if errorlevel 1 goto :fail_primp
) else (
    echo primp already installed.
)

echo.
echo [4/6] Build EXE...
echo This step can take several minutes.
pyinstaller "%SPEC_PATH%" --noconfirm --distpath "%DIST_DIR%" --workpath "%BUILD_DIR%"
if errorlevel 1 goto :fail_build
if not exist "%EXE_PATH%" goto :fail_missing_exe

echo.
echo [5/6] Ensure runtime folders...
if not exist "%DIST_APP_DIR%\data\chats" mkdir "%DIST_APP_DIR%\data\chats"
if not exist "%DIST_APP_DIR%\data\backups" mkdir "%DIST_APP_DIR%\data\backups"
if not exist "%DIST_APP_DIR%\data\hf_cache" mkdir "%DIST_APP_DIR%\data\hf_cache"
if exist "%PROJECT_ROOT%\.env" copy /Y "%PROJECT_ROOT%\.env" "%DIST_APP_DIR%\.env" >nul

echo.
echo [6/6] Create ZIP...
tar -a -c -f "%ZIP_PATH%" -C "%DIST_DIR%" jarvis
if errorlevel 1 goto :fail_zip
if not exist "%ZIP_PATH%" goto :fail_zip

echo.
echo ===============================
echo   BUILD COMPLETE
echo   EXE: %EXE_PATH%
echo   ZIP: %ZIP_PATH%
echo ===============================
popd
exit /b 0

:fail_venv
echo *** Failed to activate venv ***
popd
exit /b 1

:fail_pyinstaller
echo *** Failed to check/install PyInstaller ***
popd
exit /b 1

:fail_primp
echo *** Failed to install primp ***
popd
exit /b 1

:fail_dist_locked
echo *** Failed to remove dist folder. Another process is still using it. ***
popd
exit /b 1

:fail_zip_locked
echo *** Failed to remove existing ZIP file. Close any program using jarvis_package.zip, then try again. ***
popd
exit /b 1

:fail_build
echo *** Build failed ***
popd
exit /b 1

:fail_missing_exe
echo *** Build finished without creating jarvis.exe ***
popd
exit /b 1

:fail_zip
echo *** ZIP creation failed ***
popd
exit /b 1

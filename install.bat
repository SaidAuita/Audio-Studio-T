@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================================
echo   Audio Studio T - Установка и развертывание
echo ========================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "TEMP=%SCRIPT_DIR%temp"
set "TMP=%SCRIPT_DIR%temp"

if not exist "downloads" mkdir downloads
if not exist "temp" mkdir temp
if not exist "models\diffusion_models" mkdir "models\diffusion_models"
if not exist "models\vae" mkdir "models\vae"
if not exist "models\asr" mkdir "models\asr"
if not exist "models\hub" mkdir "models\hub"
if not exist "models\torch" mkdir "models\torch"
if not exist "output\NUM" mkdir "output\NUM"
if not exist "voices" mkdir "voices"

REM ============================================================
REM  Шаг 1: Выбор GPU для PyTorch
REM ============================================================
echo.
echo Выберите вашу конфигурацию GPU:
echo.
echo   1. NVIDIA RTX 40xx / 50xx (Ada Lovelace / Blackwell - CUDA 12.8 / cu128)
echo   2. NVIDIA RTX 30xx / 20xx (Ampere / Turing - CUDA 12.6 / cu126)
echo   3. NVIDIA GTX 10xx (Pascal - CUDA 11.8 / cu118)
echo   4. CPU only (без аппаратного ускорения NVIDIA)
echo.
set /p GPU_CHOICE="Введите номер (1-4, по умолчанию 1): "

if "%GPU_CHOICE%"=="" set "GPU_CHOICE=1"
if "%GPU_CHOICE%"=="1" goto :gpu_40xx
if "%GPU_CHOICE%"=="2" goto :gpu_30xx
if "%GPU_CHOICE%"=="3" goto :gpu_10xx
if "%GPU_CHOICE%"=="4" goto :gpu_cpu
echo Неверный выбор, используем вариант 1.
goto :gpu_40xx

:gpu_40xx
set "CUDA_VERSION=cu128"
set "CUDA_NAME=CUDA 12.8 (RTX 40xx / 50xx)"
set "TORCH_VERSION=2.7.1"
set "TORCHAUDIO_VERSION=2.7.1"
goto :gpu_done

:gpu_30xx
set "CUDA_VERSION=cu126"
set "CUDA_NAME=CUDA 12.6 (RTX 30xx / 20xx)"
set "TORCH_VERSION=2.7.1"
set "TORCHAUDIO_VERSION=2.7.1"
goto :gpu_done

:gpu_10xx
set "CUDA_VERSION=cu118"
set "CUDA_NAME=CUDA 11.8 (GTX 10xx)"
set "TORCH_VERSION=2.7.1"
set "TORCHAUDIO_VERSION=2.7.1"
goto :gpu_done

:gpu_cpu
set "CUDA_VERSION=cpu"
set "CUDA_NAME=CPU only"
set "TORCH_VERSION=2.7.1"
set "TORCHAUDIO_VERSION=2.7.1"
goto :gpu_done

:gpu_done
echo.
echo [OK] Выбрано: %CUDA_NAME%
echo.

REM ============================================================
REM  Шаг 2: Python 3.12.9 embeddable
REM ============================================================
if exist "python\python.exe" (
    echo [OK] Python уже установлен в папке python\
) else (
    echo [1/5] Скачивание изолированного Python 3.12.9...
    powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip' -OutFile 'downloads\python.zip'}"
    powershell -Command "& {Expand-Archive -Path 'downloads\python.zip' -DestinationPath 'python' -Force}"
    cd python
    if exist "python312._pth" (
        echo python312.zip> python312._pth
        echo .>> python312._pth
        echo Lib\site-packages>> python312._pth
        echo ..\Lib\site-packages>> python312._pth
        echo import site>> python312._pth
    )
    cd ..
    echo [OK] Python 3.12.9 успешно распакован и настроен
)

REM ============================================================
REM  Шаг 3: pip
REM ============================================================
if exist "python\Scripts\pip.exe" (
    echo [OK] pip уже установлен
) else (
    echo [2/5] Установка pip...
    powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'downloads\get-pip.py'}"
    python\python.exe downloads\get-pip.py --no-warn-script-location
)
python\python.exe -m pip install --upgrade pip setuptools wheel --no-warn-script-location

REM ============================================================
REM  Шаг 4: PyTorch с выбранной версией CUDA
REM ============================================================
echo [3/5] Установка PyTorch %TORCH_VERSION% (%CUDA_NAME%)...
if "%CUDA_VERSION%"=="cpu" (
    python\python.exe -m pip install torch==%TORCH_VERSION% torchaudio==%TORCHAUDIO_VERSION% --no-warn-script-location
) else (
    python\python.exe -m pip install torch==%TORCH_VERSION% torchaudio==%TORCHAUDIO_VERSION% --index-url https://download.pytorch.org/whl/%CUDA_VERSION% --no-warn-script-location
)

REM ============================================================
REM  Шаг 5: Зависимости Audio Studio T (NiceGUI, FastAPI и др.)
REM ============================================================
echo [4/5] Установка зависимостей из requirements.txt...
python\python.exe -m pip install -r requirements.txt --no-warn-script-location

REM ============================================================
REM  Шаг 6: Стартовый набор голосов (если папка пуста)
REM ============================================================
echo [5/5] Проверка библиотеки голосов...
set VOICES_EXIST=0
for %%f in (voices\*.wav voices\*.mp3) do set VOICES_EXIST=1
if "!VOICES_EXIST!"=="1" (
    echo [OK] Голосовые пресеты уже присутствуют в voices\
) else (
    echo Загрузка стартового voice-pack...
    curl.exe -L -o downloads\voice-pack.zip https://huggingface.co/datasets/nerualdreming/VibeVoice/resolve/main/voice-pack.zip
    if exist "downloads\voice-pack.zip" (
        powershell -Command "& {Expand-Archive -Path 'downloads\voice-pack.zip' -DestinationPath 'downloads\vp' -Force}"
        if exist "downloads\vp\voice-pack" (
            xcopy /E /Y /Q "downloads\vp\voice-pack\*" "voices\" >nul
        ) else (
            xcopy /E /Y /Q "downloads\vp\*" "voices\" >nul
        )
        echo [OK] Голосовые пресеты установлены
    )
)

echo.
echo ========================================================
echo   Проверка наличия моделей Drama 3
echo ========================================================
set MODELS_MISSING=0
if not exist "models\diffusion_models\*.safetensors" set MODELS_MISSING=1
if not exist "models\vae\*.safetensors" set MODELS_MISSING=1
if not exist "models\asr\*.safetensors" set MODELS_MISSING=1

if "!MODELS_MISSING!"=="1" (
    echo.
    echo ВНИМАНИЕ: Основные веса Drama 3 и Qwen3-ASR не обнаружены в папке models\.
    echo Для работы студии требуются:
    echo   - drama3_int8experts_bf16.safetensors (~38.7 ГБ)
    echo   - drama3_codec.safetensors (~1.6 ГБ)
    echo   - qwen3_asr_0.6b_bf16.safetensors (~1.6 ГБ)
    echo.
    set /p DL_MODELS="Загрузить модели с HuggingFace сейчас? (Y/N, по умолчанию N): "
    if /i "!DL_MODELS!"=="Y" (
        echo Загрузка Drama 3 Codec (~1.6 ГБ)...
        curl.exe -L -C - "https://huggingface.co/PedroMarinhoDev/Drama-3-ComfyUI/resolve/main/drama3_codec.safetensors" -o "models\vae\drama3_codec.safetensors"
        echo Загрузка Qwen3-ASR 0.6B (~1.6 ГБ)...
        curl.exe -L -C - "https://huggingface.co/PedroMarinhoDev/Qwen3-ASR-ComfyUI/resolve/main/qwen3_asr_0.6b_bf16.safetensors" -o "models\asr\qwen3_asr_0.6b_bf16.safetensors"
        echo Загрузка Drama 3 int8 MoE (~38.7 ГБ)...
        curl.exe -L -C - "https://huggingface.co/PedroMarinhoDev/Drama-3-ComfyUI/resolve/main/drama3_int8experts_bf16.safetensors" -o "models\diffusion_models\drama3_int8experts_bf16.safetensors"
        echo [OK] Модели успешно загружены!
    ) else (
        echo Модели можно добавить позже вручную в models\diffusion_models, models\vae и models\asr.
    )
) else (
    echo [OK] Все модели Drama 3 и Qwen3-ASR присутствуют в папке models\
)

echo %CUDA_VERSION%> cuda_version.txt

echo.
echo ========================================================
echo   Установка Audio Studio T успешно завершена!
echo   Для запуска приложения используйте: run.bat
echo ========================================================
pause

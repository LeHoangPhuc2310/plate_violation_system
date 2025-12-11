@echo off
echo ============================================================
echo ENABLE GPU - Install PyTorch with CUDA Support
echo ============================================================
echo.
echo Your GPU: NVIDIA GeForce RTX 3050
echo CUDA Version: 12.8
echo.
echo Step 1: Uninstall CPU-only PyTorch...
echo.
pip uninstall torch torchvision torchaudio -y

echo.
echo Step 2: Install PyTorch with CUDA 11.8...
echo.
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

echo.
echo Step 3: Verify installation...
echo.
python check_gpu.py

echo.
echo ============================================================
echo Installation complete!
echo Run: python app.py
echo ============================================================
pause


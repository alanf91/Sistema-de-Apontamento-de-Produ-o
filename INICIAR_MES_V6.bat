@echo off
cd /d "%~dp0"
python -m streamlit run J2I_MES.py --server.address 127.0.0.1 --server.port 8501
pause

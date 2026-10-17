@echo off
cd /d "%~dp0"
echo Hermes3D end-to-end test (cloud generation can take a few minutes)...
".venv\Scripts\python.exe" tests\win_hermes3d_e2e.py
echo Done. See tests\selftest_out\hermes3d_e2e.txt

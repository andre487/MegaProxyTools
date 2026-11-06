@echo off
setlocal DisableDelayedExpansion
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    set "megaproxy_python=python"
    goto install
)
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    set "megaproxy_python=py -3"
    goto install
)
echo Python 3.10+ is required. Install it with:
echo   winget install --id Python.Python.3.14 --exact
echo Then reopen your terminal and run install.cmd again.
exit /b 1

:install
%megaproxy_python% "%~dp0win\install.py" %*
exit /b %errorlevel%

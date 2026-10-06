@echo off
rem Build AION2_CHT.exe with the .NET Framework compiler that ships with Windows.
rem The language pack (langpack\L10NString.dat) is embedded into the exe.
setlocal
cd /d "%~dp0"
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
"%CSC%" /nologo /target:winexe /optimize+ /codepage:65001 /out:AION2_CHT.exe /resource:langpack\L10NString.dat,cht.dat /reference:System.Windows.Forms.dll /reference:System.Drawing.dll AION2_CHT.cs
if errorlevel 1 exit /b 1
echo Built AION2_CHT.exe

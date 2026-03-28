; hledger-textual Windows Installer
; Built with NSIS (https://nsis.sourceforge.io)
;
; Produces two optional installer flavors via /DBUNDLED_HLEDGER define:
;   - Full bundle  : includes hledger.exe  (no hledger pre-installation needed)
;   - Slim bundle  : hledger.exe not included (requires hledger on PATH)

!ifndef APPVERSION
  !define APPVERSION "0.0.0"
!endif

!ifndef BUNDLED_HLEDGER
  !define BUNDLED_HLEDGER 0
!endif

!if ${BUNDLED_HLEDGER} == 1
  !define OUTFILE "hledger-textual-${APPVERSION}-windows-x64-bundled.exe"
  !define PRODUCT_NAME "hledger-textual (bundled)"
!else
  !define OUTFILE "hledger-textual-${APPVERSION}-windows-x64-slim.exe"
  !define PRODUCT_NAME "hledger-textual (slim)"
!endif

!define INSTDIR_DEFAULT "$PROGRAMFILES64\hledger-textual"
!define REG_UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\hledger-textual"

Name "${PRODUCT_NAME} ${APPVERSION}"
OutFile "${OUTFILE}"
InstallDir "${INSTDIR_DEFAULT}"
InstallDirRegKey HKLM "Software\hledger-textual" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

;------------------------------------------------------------------
; Pages
;------------------------------------------------------------------
!include "MUI2.nsh"

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\hledger-textual.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch hledger-textual now"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

;------------------------------------------------------------------
; Install section
;------------------------------------------------------------------
Section "Install" SecInstall
  SetOutPath "$INSTDIR"

  ; Copy all PyInstaller output files
  File /r "dist\hledger-textual\*.*"

  !if ${BUNDLED_HLEDGER} == 1
    ; Include the bundled hledger.exe
    File "hledger.exe"
  !endif

  ; Add install dir to system PATH
  EnVar::AddValue "PATH" "$INSTDIR"

  ; Write registry keys for uninstaller
  WriteRegStr HKLM "Software\hledger-textual" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${REG_UNINST}" "DisplayName" "hledger-textual ${APPVERSION}"
  WriteRegStr HKLM "${REG_UNINST}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "${REG_UNINST}" "DisplayVersion" "${APPVERSION}"
  WriteRegStr HKLM "${REG_UNINST}" "Publisher" "Michele Broggi"
  WriteRegStr HKLM "${REG_UNINST}" "URLInfoAbout" "https://github.com/thesmokinator/hledger-textual"
  WriteRegDWORD HKLM "${REG_UNINST}" "NoModify" 1
  WriteRegDWORD HKLM "${REG_UNINST}" "NoRepair" 1

  ; Start Menu shortcut
  CreateDirectory "$SMPROGRAMS\hledger-textual"
  CreateShortcut "$SMPROGRAMS\hledger-textual\hledger-textual.lnk" \
    "$INSTDIR\hledger-textual.exe" "" "$INSTDIR\hledger-textual.exe"
  CreateShortcut "$SMPROGRAMS\hledger-textual\Uninstall.lnk" \
    "$INSTDIR\uninstall.exe"

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

;------------------------------------------------------------------
; Uninstall section
;------------------------------------------------------------------
Section "Uninstall"
  ; Remove from PATH
  EnVar::DeleteValue "PATH" "$INSTDIR"

  ; Remove files
  RMDir /r "$INSTDIR"

  ; Remove Start Menu shortcuts
  RMDir /r "$SMPROGRAMS\hledger-textual"

  ; Remove registry keys
  DeleteRegKey HKLM "Software\hledger-textual"
  DeleteRegKey HKLM "${REG_UNINST}"
SectionEnd

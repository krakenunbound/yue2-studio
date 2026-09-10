; The app writes models and songs next to its executable. Use a per-user,
; writable destination and keep user-created data out of the payload manifest.
!macro NSIS_HOOK_PREINSTALL
  ClearErrors
  CreateDirectory "$INSTDIR"
  GetTempFileName $0 "$INSTDIR"
  ${If} ${Errors}
    MessageBox MB_ICONSTOP "YuE2 Studio needs a writable installation folder for songs and model downloads. Choose a folder you own, such as the default location."
    Abort
  ${EndIf}
  Delete "$0"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  CreateDirectory "$INSTDIR\outputs\library"
  CreateDirectory "$INSTDIR\outputs\logs"
  CreateDirectory "$INSTDIR\outputs\settings"
  CreateDirectory "$INSTDIR\outputs\downloads"
  CreateDirectory "$INSTDIR\outputs\recovery"
  CreateDirectory "$INSTDIR\models\YuE2-Vae"
  CreateDirectory "$INSTDIR\models\lyrics"
  CreateDirectory "$INSTDIR\models\cover_art"
  CreateDirectory "$INSTDIR\models\stems"
  CreateDirectory "$INSTDIR\models\sound_effects"
!macroend

; Never recursively remove the app directory: it contains the user's library,
; downloaded models and local key vault. Tauri removes only its packaged files.
!macro NSIS_HOOK_POSTUNINSTALL
!macroend

' start_backend_hidden.vbs
' Hidden-window launcher for jren-campus-assistant backend (logon autostart)
' 2nd arg 0 = no window. NOTE: keep this file ASCII-only (WSH parses in ANSI codepage)
' Uses absolute path; if the repo moves, update this file (see docs/mcp-server.md)
Set sh = CreateObject("Wscript.Shell")
sh.Run """C:\Users\LEO\Desktop\jren-files\backend\scripts\start_backend.bat""", 0, False

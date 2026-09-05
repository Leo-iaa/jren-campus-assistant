' start_workbuddy_delayed.vbs - delayed logon startup for WorkBuddy.
' Waits until the jren-campus-assistant backend (127.0.0.1:28070) answers
' /health, then launches WorkBuddy. This closes the boot race where the
' WorkBuddy daemon starts before the jren backend and MCP connector
' discovery fails (ECONNREFUSED -> "Ensured connectors: connected=0").
'
' IMPORTANT: disable WorkBuddy's own in-app autostart, otherwise it will
' start twice (once immediately by the app, once from this script).
' Keep this file ASCII-only (wscript parses in ANSI codepage).

Option Explicit

Dim http, sh, i, ok
Const HEALTH_URL = "http://127.0.0.1:28070/health"
Const REQ_TIMEOUT_MS = 2000
Const MAX_ATTEMPTS = 30   ' 30 x 3s = max ~90s wait
Const POLL_MS = 3000

Set sh = CreateObject("WScript.Shell")
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
http.setTimeouts REQ_TIMEOUT_MS, REQ_TIMEOUT_MS, REQ_TIMEOUT_MS, REQ_TIMEOUT_MS

ok = False
For i = 1 To MAX_ATTEMPTS
    On Error Resume Next
    http.Open "GET", HEALTH_URL, False
    http.Send ""
    If Err.Number = 0 Then
        If http.status = 200 Then ok = True
    End If
    Err.Clear
    On Error GoTo 0
    If ok Then Exit For
    WScript.Sleep POLL_MS
Next

' Launch WorkBuddy regardless of the health result (never block logon).
sh.Run """D:\workbuddy\WorkBuddy.exe""", 1, False

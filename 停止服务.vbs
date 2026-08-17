' ============================================================
'  停止服务（无黑窗口）
'  双击本文件即可关闭后台运行的筛选工具（释放 8000 端口）。
' ============================================================
Option Explicit
On Error Resume Next

Dim ws, exec, out, lines, i, parts, p, found
Set ws = CreateObject("WScript.Shell")

found = False

Set exec = ws.Exec("cmd /c netstat -ano | findstr /i "" :8000 """)
If Not exec.StdOut.AtEndOfStream Then out = exec.StdOut.ReadAll
If Len(out) > 0 Then
    lines = Split(out, vbCrLf)
    For i = 0 To UBound(lines)
        If InStr(lines(i), "LISTENING") > 0 Then
            parts = Split(lines(i))
            p = Trim(parts(UBound(parts)))
            If IsNumeric(p) And Len(p) > 0 Then
                ws.Run "taskkill /PID " & p & " /F", 0, True
                found = True
            End If
        End If
    Next
End If

If found Then
    ws.Popup "筛选工具已停止。", 0, "A股蜡烛图形态筛选工具", 0x40
Else
    ws.Popup "没有发现正在运行的筛选工具（端口 8000 未被占用）。", _
             0, "A股蜡烛图形态筛选工具", 0x40
End If

' ============================================================
'  一键启动（无黑窗口）
'  双击本文件即可：自动找 / 装运行环境，后台启动筛选工具，
'  并自动打开浏览器。整个过程不弹出任何命令行黑窗口。
'  （若仍失败，会弹出系统消息框告诉你原因。）
' ============================================================
Option Explicit
On Error Resume Next

Dim fso, ws, root, ps1, launcher
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws  = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName) & "\"

ps1      = root & "scripts\下载运行环境.ps1"
launcher = root & "launcher.pyw"

Function Exists(p)
    Exists = fso.FileExists(p)
End Function

Function Q(s)
    Q = """" & s & """"
End Function

' ---- 找 Python（优先程序自带的便携运行环境，用户无需安装任何东西） ----
Dim py, oExec, line
py = ""

If Exists(root & "runtime\pythonw.exe") Then
    py = root & "runtime\pythonw.exe"
ElseIf Exists(root & "runtime\python.exe") Then
    py = root & "runtime\python.exe"
ElseIf Exists("C:\Users\Edwar\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe") Then
    py = "C:\Users\Edwar\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
Else
    ' 让系统去找一个已安装的 python
    Set oExec = ws.Exec("cmd /c where python 2>nul")
    If Not oExec.StdOut.AtEndOfStream Then
        line = oExec.StdOut.ReadLine
        If Len(line) > 0 Then py = line
    End If
End If

' ---- 没有任何 Python：自动下载一个便携运行环境（隐藏窗口进行） ----
If py = "" Then
    If Exists(ps1) Then
        ws.Run "powershell -NoProfile -ExecutionPolicy Bypass -File " & Q(ps1), 0, True
        If Exists(root & "runtime\pythonw.exe") Then
            py = root & "runtime\pythonw.exe"
        ElseIf Exists(root & "runtime\python.exe") Then
            py = root & "runtime\python.exe"
        End If
    End If
End If

' ---- 仍然没有 Python：弹窗告知，不再闪退 ----
If py = "" Then
    ws.Popup "没有找到可用的运行环境，且自动下载失败。" & vbCrLf & vbCrLf & _
             "请检查网络连接后，重新双击「一键启动」。" & vbCrLf & _
             "若仍失败，可右键本文件 -> 属性 -> 勾选“解除锁定” -> 确定后再试。", _
             0, "A股蜡烛图形态筛选工具", 0x10
    WScript.Quit 1
End If

' ---- 后台、无窗口地启动启动器 ----
ws.Run Q(py) & " " & Q(launcher), 0, False
WScript.Quit 0

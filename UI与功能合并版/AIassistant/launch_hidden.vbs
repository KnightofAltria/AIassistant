Option Explicit
Dim shell, command
Set shell = CreateObject("WScript.Shell")
command = "cmd.exe /c """"" & WScript.Arguments(0) & """ --hidden"""
shell.Run command, 0, False

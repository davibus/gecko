Option Explicit

' Task Scheduler runs this with wscript.exe //B. Run(..., 0, True) starts the
' existing PowerShell collector hidden, waits, and returns its exit code.
On Error Resume Next

Dim shell, files, usageDir, logDir, logPath, stamp, logFile
Dim powershell, command, exitCode, errorText
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
usageDir = files.GetParentFolderName(WScript.ScriptFullName)
logDir = files.BuildPath(usageDir, "logs")
If Not files.FolderExists(logDir) Then files.CreateFolder logDir
If Err.Number <> 0 Then Fail "Cannot create collector log directory: " & Err.Description

stamp = Year(Now) & Right("0" & Month(Now), 2) & Right("0" & Day(Now), 2) & "-" & _
        Right("0" & Hour(Now), 2) & Right("0" & Minute(Now), 2) & Right("0" & Second(Now), 2)
logPath = files.BuildPath(logDir, "collector-" & stamp & ".log")
Set logFile = files.OpenTextFile(logPath, 8, True)
If Err.Number <> 0 Then Fail "Cannot open collector log: " & Err.Description
logFile.WriteLine "Started: " & Now
logFile.Close
If Err.Number <> 0 Then Fail "Cannot write collector log: " & Err.Description

powershell = files.BuildPath(shell.ExpandEnvironmentStrings("%SystemRoot%"), _
                            "System32\WindowsPowerShell\v1.0\powershell.exe")
command = Quote(powershell) & " -NoProfile -NonInteractive -WindowStyle Hidden" & _
          " -ExecutionPolicy Bypass -File " & Quote(files.BuildPath(usageDir, "run_collector.ps1")) & _
          " 1>>" & Quote(logPath) & " 2>&1"
command = Quote(files.BuildPath(shell.ExpandEnvironmentStrings("%SystemRoot%"), "System32\cmd.exe")) & _
          " /D /S /C " & Quote(command)
exitCode = shell.Run(command, 0, True)
If Err.Number <> 0 Then Fail "Cannot launch collector: " & Err.Description

Set logFile = files.OpenTextFile(logPath, 8, True)
If Err.Number <> 0 Then Fail "Cannot append collector result: " & Err.Description
logFile.WriteLine "Finished: " & Now & "; exit code: " & exitCode
logFile.Close
If Err.Number <> 0 Then Fail "Cannot write collector result: " & Err.Description
WScript.Quit exitCode

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function

Sub Fail(message)
    errorText = message
    Err.Clear
    shell.LogEvent 1, "Gecko Main Codex Usage Collector: " & errorText
    WScript.Quit 1
End Sub

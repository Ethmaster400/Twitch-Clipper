' Runs scripts\run_claud.bat with no visible window (used by the scheduled task).
' Waits for it to finish, so the task shows as Running until the run is done.
Set shell = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.Run """" & here & "\run_claud.bat""", 0, True

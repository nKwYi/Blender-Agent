Set-Location 'E:\Three JS\Blender Agent'
$B = 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
$root = 'E:\Three JS\Blender Agent'
$p = Start-Process -FilePath $B -WorkingDirectory $root -ArgumentList '--factory-startup','-P','dev\gui_check_custom.py' -WindowStyle Minimized -PassThru -Wait -RedirectStandardOutput "$root\dev\out\acc_o.txt" -RedirectStandardError "$root\dev\out\acc_e.txt"
Write-Output "EXITCODE=$($p.ExitCode)"

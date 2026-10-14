import subprocess, sys
out = subprocess.check_output([
    'powershell', '-NoProfile', '-Command',
    "Get-WmiObject Win32_Process -Filter \"name='blender.exe'\" | Select-Object ProcessId, CommandLine | Format-List"
], text=True, encoding='utf-8', errors='ignore')
sys.stdout.buffer.write(out.encode('utf-8'))

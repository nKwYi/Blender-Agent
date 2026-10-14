import subprocess, os

B = r'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
root = r'E:\Three JS\Blender Agent'
script = os.path.join(root, 'dev', 'check_native_box.py')

p = subprocess.run([B, '--factory-startup', '-P', script], cwd=root)
print('EXITCODE:', p.returncode)

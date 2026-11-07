import re
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('web_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', content, re.DOTALL | re.IGNORECASE)
print(f'Total inline script blocks: {len(scripts)}')

errors = 0
for idx, s in enumerate(scripts, 1):
    # If the script contains double braces {{, it is from a python f-string
    if '{{' in s or '}}' in s:
        cleaned = s.replace('{{', '__DBL_L__').replace('}}', '__DBL_R__')
        cleaned = re.sub(r'\{[^{}\r\n]*\}', '0', cleaned)
        cleaned = cleaned.replace('__DBL_L__', '{').replace('__DBL_R__', '}')
    else:
        # Not an f-string, or single braces only. Just test as-is
        cleaned = s

    proc = subprocess.run(['node', '--check'], input=cleaned.encode('utf-8'), capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode('utf-8', errors='ignore')
        print(f'Script #{idx} failed syntax check:\n{err[:200]}')
        errors += 1

print(f'Verification finished: {len(scripts)-errors}/{len(scripts)} passed, errors: {errors}')
if errors == 0:
    print('ALL JAVASCRIPT BLOCKS PASSED SYNTAX CHECK WITH ZERO ERRORS (100% PASS)!')

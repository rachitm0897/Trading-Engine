from pathlib import Path
import sys

PARTS = ('PASSWORD','SECRET','TOKEN','API_KEY','ENCRYPTION_KEY','IBKR_USERNAME','NOVNC_PASSWORD','AUTHORIZATION')
SUFFIXES = {'.txt','.json','.html','.log','.csv','.xml','.md','.cmd','.py','.js'}

def env_values(path):
    values, names = [], set()
    for raw in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        name, value = line.split('=',1); name=name.strip(); value=value.strip()
        if not any(p in name.upper() for p in PARTS): continue
        if len(value)>=2 and value[0]==value[-1] and value[0] in "'\"": value=value[1:-1]
        for candidate in {value, value.replace('$$','$')}:
            if candidate and len(candidate)>=4: values.append((candidate,name)); names.add(name)
    values.sort(key=lambda x: len(x[0]), reverse=True)
    return values, sorted(names)

def main():
    env_file, root = Path(sys.argv[1]), Path(sys.argv[2])
    replacements, names = env_values(env_file)
    files=hits=0
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES: continue
        files += 1
        text = path.read_text(encoding='utf-8', errors='ignore'); original=text
        for value,name in replacements:
            count=text.count(value)
            if count: text=text.replace(value,f'[REDACTED_{name}]'); hits += count
        if text != original: path.write_text(text, encoding='utf-8')
    print('Scanned text files:', files); print('Exact sensitive-value replacements:', hits)
    print('Sensitive variable names considered:'); [print(' ',name) for name in names]

if __name__=='__main__': main()

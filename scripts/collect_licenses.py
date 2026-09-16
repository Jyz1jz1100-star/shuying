"""Collect installed dependency license files into the local packaging input."""
from pathlib import Path
import importlib.metadata as metadata
import shutil
import sys
import urllib.request

root=Path(__file__).resolve().parents[1]
target=root/'vendor/licenses'
target.mkdir(parents=True,exist_ok=True)
for line in (root/'requirements-lock.txt').read_text().splitlines():
    if not line or line.startswith('#'):
        continue
    name=line.split('==')[0]
    distribution=metadata.distribution(name)
    for file in distribution.files or []:
        if 'license' in str(file).lower() or 'copying' in str(file).lower() or Path(str(file)).name.lower().startswith('notice'):
            source=Path(distribution.locate_file(file))
            if source.is_file() and source.stat().st_size < 2_000_000:
                destination=target/name/str(file).replace('..','_').replace('/','_').replace('\\','_')
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,destination)
for source in (root/'node_modules/.pnpm').glob('*/node_modules/*/LICENSE*'):
    destination=target/'frontend'/source.parent.name/source.name
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.is_file():
    shutil.copyfile(python_license,target/'Python-LICENSE.txt')
runtime_license=target/'whisper.cpp-LICENSE'
if not runtime_license.exists():
    url='https://raw.githubusercontent.com/lemonade-sdk/whisper.cpp-rocm/v1.8.4/LICENSE'
    with urllib.request.urlopen(url,timeout=30) as response:
        data=response.read(100000)
    if b'MIT License' not in data:
        raise RuntimeError('Unexpected whisper.cpp license response')
    runtime_license.write_bytes(data)
print('Collected dependency notices in vendor/licenses')

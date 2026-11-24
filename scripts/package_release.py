"""Package only the application and notices; never include downloaded textures."""
import argparse
import hashlib
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--dist', type=Path, default=Path('dist'))
parser.add_argument('--output', type=Path, default=Path('release'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
required = ['MaterialConverter.exe', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']
for name in required:
    if not (args.dist / name).is_file():
        raise FileNotFoundError(args.dist / name)
notices = sorted(p for p in (args.dist / 'licenses').rglob('*') if p.is_file())
if not notices:
    raise RuntimeError('Dependency licence notices are missing.')
archive = args.output / 'MaterialConverter-Windows.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
    for name in required:
        package.write(args.dist / name, Path('MaterialConverter') / name)
    for file in notices:
        package.write(file, Path('MaterialConverter') / file.relative_to(args.dist))
with zipfile.ZipFile(archive) as package:
    if package.testzip() is not None:
        raise RuntimeError('Release archive verification failed.')
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(args.output / 'SHA256SUMS.txt').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
print('Packaged', archive, 'SHA256', digest)

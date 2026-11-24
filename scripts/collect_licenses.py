"""Collect notices from the packages used by the standalone application."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

destination = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist/licenses')
destination.mkdir(parents=True, exist_ok=True)
for name in ('pillow', 'numpy', 'OpenImageIO', 'tifffile', 'pyinstaller'):
    package = distribution(name)
    for file in package.files or ():
        if any(word in str(file).lower() for word in ('license', 'copying', 'notice')):
            source = Path(package.locate_file(file))
            if source.is_file():
                target = destination / name / str(file).replace('..', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
for source in Path(sys.base_prefix).glob('LICENSE*'):
    if source.is_file():
        shutil.copyfile(source, destination / source.name)
for folder in ('tcl', 'Library'):
    base = Path(sys.base_prefix) / folder
    if base.is_dir():
        for source in base.glob('**/license.terms'):
            target = destination / 'TclTk' / source.parent.name / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
print('Collected dependency notices in', destination)

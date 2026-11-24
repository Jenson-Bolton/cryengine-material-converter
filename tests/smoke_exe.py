"""Exercise the frozen Windows executable without requiring CRYENGINE in CI."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
from PIL import Image
import tifffile

def png(color):
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(buffer, format='PNG')
    return buffer.getvalue()

exe = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='material_converter_smoke_') as temporary:
    root = Path(temporary)
    source = root / 'material.zip'
    output = root / 'converted'
    with zipfile.ZipFile(source, 'w') as archive:
        for role, color in [('basecolor', (180, 120, 60)), ('normal', (128, 64, 255)),
                            ('roughness', (200, 200, 200)), ('ambientOcclusion', (220, 220, 220))]:
            archive.writestr('nested/test_' + role + '.png', png(color))
    process = subprocess.run([str(exe), '--convert', str(source), '--output', str(output),
                              '--no-dds', '--normal-format', 'OpenGL'], timeout=120)
    if process.returncode:
        error_file = output / 'last-error.txt'
        detail = error_file.read_text() if error_file.is_file() else 'No diagnostic file was written.'
        raise RuntimeError('Frozen EXE failed: ' + detail)
    result = json.loads((output / 'last-result.json').read_text())
    material = Path(result[0])
    assert (material / 'test.mtl').is_file()
    assert (material / 'test_ao.tif').is_file()
    normal = tifffile.imread(material / 'test_ddna.tif')
    assert normal.dtype == np.uint16
    np.testing.assert_allclose(normal[0, 0] / 65535, [128/255, 191/255, 1, 55/255], atol=1/65535)
print('PASS: frozen Windows EXE loads its libraries and converts a ZIP correctly.')

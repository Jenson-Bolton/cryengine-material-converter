import io
import tempfile
import zipfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
import tifffile
import OpenImageIO as oiio
from converter import convert, scan

def png(rgb):
    b=io.BytesIO(); Image.new('RGB',(8,8),rgb).save(b,format='PNG'); return b.getvalue()

with tempfile.TemporaryDirectory() as t:
    d=Path(t)
    p=d/'partial.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('textures/test_nor_gl_1k.png',png((128,64,255)))
        z.writestr('textures/test_arm_1k.png',png((200,100,0)))
        z.writestr('../../ignored.blend',b'never extracted')
    f=convert(p,d/'out',compile_dds=False,max_size=0,log=lambda _:None)[0]
    a=tifffile.imread(f/'test_ddna.tif')
    assert a.dtype==np.uint16
    np.testing.assert_allclose(a[0,0]/65535,[128/255,191/255,1,155/255],atol=1/65535)
    spec=tifffile.imread(f/'test_spec.tif')
    assert abs(spec[0,0,0]/65535-.220916)<.0001
    assert './test_ddna.tif' in (f/'test.mtl').read_text()
    assert not (d/'ignored.blend').exists()
    second=convert(p,d/'out',compile_dds=False,max_size=0,log=lambda _:None)[0]
    assert second.name=='test_2'
    # EXR-only partial set exercises linear colour, DirectX normals and decode support.
    exr=d/'source.exr'
    out=oiio.ImageOutput.create(str(exr)); out.open(str(exr),oiio.ImageSpec(8,8,3,oiio.FLOAT))
    out.write_image(np.full((8,8,3),.18,dtype=np.float32)); out.close()
    p2=d/'exr.zip'
    with zipfile.ZipFile(p2,'w') as z: z.write(exr,'exr_only_diff_1k.exr')
    f2=convert(p2,d/'out',compile_dds=False,log=lambda _:None)[0]
    assert abs(tifffile.imread(f2/'exr_only_diff.tif')[0,0,0]/65535-.461356)<.0001
    assert np.all(tifffile.imread(f2/'exr_only_ddna.tif')[...,3]==32768)
    # Separate roughness takes precedence over ARM; DX takes precedence over GL.
    with zipfile.ZipFile(p,'a') as z:
        z.writestr('textures/test_rough_1k.jpg',png((230,230,230)))
        z.writestr('textures/test_nor_dx_1k.png',png((128,42,255)))
    f3=convert(p,d/'out',compile_dds=False,log=lambda _:None)[0]
    a=tifffile.imread(f3/'test_ddna.tif')[0,0]/65535
    np.testing.assert_allclose(a,[128/255,42/255,1,25/255],atol=1/65535)
    # TextureCan aliases, metadata filtering and auxiliary scattering preservation.
    tc=d/'texturecan.zip'
    with zipfile.ZipFile(tc,'w') as z:
        for role,value in [('color',(180,120,60)),('normal_directx',(128,42,255)),
                           ('normal_opengl',(128,213,255)),('height',(90,90,90)),
                           ('roughness',(230,230,230)),('scattering',(70,70,70))]:
            file='fabric_0012_'+role+'_2k.png'
            z.writestr(file,png(value))
            z.writestr('__MACOSX/._'+file,b'not an image')
        z.writestr('._orphan_color_2k.jpg',b'not an image either')
    groups=scan(tc)
    assert set(groups)=={'fabric_0012'}
    assert set(groups['fabric_0012'])=={'diff','nor_dx','nor_gl','disp','rough','scattering'}
    f4=convert(tc,d/'out',compile_dds=False,log=lambda _:None)[0]
    np.testing.assert_allclose(tifffile.imread(f4/'fabric_0012_diff.tif')[0,0]/65535,[180/255,120/255,60/255],atol=1/65535)
    np.testing.assert_allclose(tifffile.imread(f4/'fabric_0012_ddna.tif')[0,0]/65535,[128/255,42/255,1,25/255],atol=1/65535)
    np.testing.assert_allclose(tifffile.imread(f4/'fabric_0012_displ.tif')[0,0]/65535,[90/255]*4,atol=1/65535)
    assert (f4/'fabric_0012_scattering.tif').is_file()
    assert 'manual shader setup' in (f4/'conversion.json').read_text()
    # 3DTextures.me: nested folder, no resolution suffix, camelCase AO and generic normal.
    three=d/'3dtextures.zip'
    with zipfile.ZipFile(three,'w') as z:
        for role,value in [('basecolor',(200,150,100)),('normal',(128,64,255)),
                           ('height',(90,90,90)),('roughness',(180,180,180)),
                           ('ambientOcclusion',(220,220,220))]:
            z.writestr('Glass_Frosted_001_SD/Glass_Frosted_001_'+role+'.png',png(value))
        z.writestr('Glass_Frosted_001_SD/Material_1619.jpg',b'preview must be ignored')
    groups=scan(three)
    assert set(groups)=={'glass_frosted_001'}
    assert set(groups['glass_frosted_001'])=={'diff','normal','disp','rough','ao'}
    f5=convert(three,d/'out',compile_dds=False,log=lambda _:None)[0]
    np.testing.assert_allclose(tifffile.imread(f5/'glass_frosted_001_ddna.tif')[0,0]/65535,[128/255,191/255,1,75/255],atol=1/65535)
    assert (f5/'glass_frosted_001_ao.tif').is_file()
    assert 'opaque Illum' in (f5/'GLASS_SETUP.txt').read_text()
    f6=convert(three,d/'out',compile_dds=False,normal_format='DirectX',log=lambda _:None)[0]
    np.testing.assert_allclose(tifffile.imread(f6/'glass_frosted_001_ddna.tif')[0,0]/65535,[128/255,64/255,1,75/255],atol=1/65535)
    empty=d/'empty.zip'
    with zipfile.ZipFile(empty,'w') as z: z.writestr('nothing.txt','no maps')
    try: scan(empty)
    except ValueError: pass
    else: raise AssertionError('Empty archive should fail clearly')
    print('PASS: 3DTextures.me nested maps, generic normals and overrides, glass notes, TextureCan aliases, AppleDouble filtering, scattering preservation, Poly Haven partial ARM/GL, missing maps, channel packing, 16-bit TIFF, EXR, map priority, safe archive reading, existing outputs, empty archive.')

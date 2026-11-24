"""CRYENGINE Material Converter. ZIP texture maps to engine materials."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import threading
import traceback
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import OpenImageIO as oiio
from PIL import Image
import tifffile

APP = 'CRYENGINE Material Converter'
def find_rc():
    """Use an explicit override, an adjacent engine, or a common install location."""
    override = os.environ.get('CRYENGINE_RC', '')
    if override and Path(override).is_file():
        return override
    home = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    for parent in (home, *home.parents):
        candidate = parent/'Tools'/'rc'/'rc.exe'
        if candidate.is_file(): return str(candidate)
    for root in (Path('D:/CRYENGINE/Engines'), Path('C:/CRYENGINE/Engines')):
        if not root.is_dir(): continue
        candidates = []
        for pattern in ('*/Tools/rc/rc.exe','*/*/Tools/rc/rc.exe','*/*/*/Tools/rc/rc.exe'):
            candidates.extend(root.glob(pattern))
        if candidates: return str(sorted(candidates,reverse=True)[0])
    return ''

RC_DEFAULT = find_rc()
ALIASES = {'albedo':'diff','basecolor':'diff','color':'diff','colour':'diff',
           'roughness':'rough','normal_dx':'nor_dx','normal_gl':'nor_gl',
           'normal_directx':'nor_dx','normal_opengl':'nor_gl',
           'displacement':'disp','height':'disp','metallic':'metal','metalness':'metal',
           'specular':'spec','alpha':'opacity','emissive':'emission',
           'ambientocclusion':'ao','ambient_occlusion':'ao'}
ROLES = {'diff','nor_dx','nor_gl','normal','rough','arm','ao','disp','metal','spec','opacity','emission','scattering'}
PATTERN = re.compile(r'^(.*?)_(' + '|'.join(sorted(ROLES | ALIASES.keys(),key=lambda s:(-len(s),s))) + r')(?:_(\d+)[kK])?$', re.I)
EXT = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.exr', '.bmp', '.tga'}

def scan(path):
    groups = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            p = Path(info.filename.replace('\\','/'))
            # AppleDouble files are metadata, even when their names end in .png/.jpg.
            if '__MACOSX' in p.parts or p.name.startswith('._'):
                continue
            if p.suffix.lower() not in EXT or info.is_dir():
                continue
            m = PATTERN.match(p.stem)
            if not m:
                continue
            name, role, res = m.groups()
            role = ALIASES.get(role.lower(), role.lower())
            key = re.sub('[^a-z0-9_-]+', '_', name.lower()).strip('_') or 'material'
            # Prefer highest supplied resolution, then lossless PNG, EXR, TIFF, JPG.
            score = (int(res or 0), {'.png':6,'.exr':5,'.tif':4,'.tiff':4,'.tga':3,'.bmp':2}.get(p.suffix.lower(),1), info.filename)
            old = groups.setdefault(key, {}).get(role)
            if old is None or score > old[0]:
                groups[key][role] = (score, info)
    if not groups:
        raise ValueError('No supported texture maps found. Expected names such as stone_diff_2k.png, fabric_color_2k.jpg or Glass_Frosted_001_basecolor.jpg.')
    return groups

def read_image(z, info, temp, size=None, color=False):
    if info.file_size > 2 * 1024**3:
        raise ValueError('Texture exceeds the 2 GB per-file limit: ' + info.filename)
    p = Path(temp) / ('input' + Path(info.filename).suffix.lower())
    # Never extract archive paths or execute model/material files.
    with z.open(info) as source, p.open('wb') as dest:
        shutil.copyfileobj(source, dest, 1024*1024)
    inp = oiio.ImageInput.open(str(p))
    if not inp:
        raise ValueError('Cannot decode ' + info.filename + ': ' + oiio.geterror())
    try:
        spec = inp.spec()
        if spec.width * spec.height > 70000000 or spec.nchannels > 16:
            raise ValueError('Texture exceeds the 70 megapixel / 16 channel limit.')
        a = inp.read_image(format=oiio.FLOAT)
        if a is None:
            raise ValueError('Cannot read ' + info.filename)
    finally:
        inp.close()
    a = np.asarray(a, dtype=np.float32)
    if a.ndim == 2:
        a = a[...,None]
    a = np.nan_to_num(a, nan=0., posinf=1., neginf=0.)
    if color and p.suffix == '.exr':
        rgb = a[...,:3]
        a[...,:3] = np.where(rgb <= .0031308, rgb * 12.92, 1.055 * np.maximum(rgb,0)**(1/2.4) - .055)
    if size and (a.shape[1], a.shape[0]) != size:
        a = np.stack([np.asarray(Image.fromarray(a[...,c]).resize(size, Image.Resampling.BILINEAR)) for c in range(a.shape[2])], axis=-1)
    return np.clip(a, 0, 1)

def rgb(a):
    return np.repeat(a[...,:1],3,axis=2) if a.shape[2] < 3 else a[...,:3]

def linear(a):
    return np.where(a <= .04045, a/12.92, ((a+.055)/1.055)**2.4)

def srgb(a):
    return np.where(a <= .0031308, a*12.92, 1.055*np.maximum(a,0)**(1/2.4)-.055)

def save_tif(path, a, preset):
    # Match the Photoshop IPTC resource emitted by CRYENGINE's /savepreset.
    settings = ('/preset=' + preset).encode('ascii')
    iptc = b'\x1c\x02\x00\x00\x02\x00\x02\x1c\x02\x28' + struct.pack('>H',len(settings)) + settings
    resource = b'8BIM\x04\x04\x00\x00' + struct.pack('>I',len(iptc)) + iptc
    pixels = np.rint(np.clip(a,0,1)*65535).astype(np.uint16)
    tifffile.imwrite(path,pixels,photometric='rgb',metadata=None,description='/preset='+preset,
                     extrasamples=['unassalpha'] if pixels.shape[2]==4 else None,
                     extratags=[(34377,'B',len(resource),resource,False)])

def convert(zip_path, output, rc=RC_DEFAULT, compile_dds=True, max_size=4096, bake_ao=False, log=print, normal_format='OpenGL'):
    zip_path, output = Path(zip_path), Path(output).resolve()
    groups = scan(zip_path)
    if normal_format not in ('OpenGL','DirectX'):
        raise ValueError('Unlabelled normal format must be OpenGL or DirectX.')
    if compile_dds and not Path(rc).is_file():
        raise ValueError('Resource Compiler not found. Browse to your engine Tools/rc/rc.exe, or disable DDS compilation.')
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with zipfile.ZipFile(zip_path) as z, tempfile.TemporaryDirectory(prefix='phcry_') as temp:
        for name, maps in groups.items():
            folder = output / name
            suffix = 2
            while folder.exists():
                folder = output / (name + '_' + str(suffix)); suffix += 1
            folder.mkdir()
            messages = []
            def note(s):
                messages.append(s); log(s)
            try:
                note('Converting ' + name)
                anchor = next((maps[k][1] for k in ('diff','nor_dx','nor_gl','normal','rough','arm','disp') if k in maps), next(iter(maps.values()))[1])
                first = read_image(z,anchor,temp)
                w,h = first.shape[1],first.shape[0]
                scale = min(1, max_size/max(w,h)) if max_size else 1
                size = (max(1,round(w*scale)),max(1,round(h*scale)))
                del first
                shape = (size[1],size[0],1)
                def get(role, color=False):
                    if role not in maps: return None
                    note('  ' + role + ': ' + maps[role][1].filename)
                    return read_image(z,maps[role][1],temp,size,color)
                base = get('diff',True)
                if base is None:
                    base = np.full(shape[:-1]+(3,), .5, np.float32); note('  Missing diffuse: neutral grey used.')
                base = rgb(base)
                arm = get('arm') if any(k not in maps for k in ('rough','metal','ao')) else None
                rough = get('rough')
                rough = rough[...,:1] if rough is not None else (arm[...,1:2] if arm is not None and arm.shape[2]>=3 else np.full(shape,.5,np.float32))
                if 'rough' not in maps: note('  Roughness: ARM green used.' if arm is not None else '  Missing roughness: 0.5 used.')
                metal = get('metal')
                metal = metal[...,:1] if metal is not None else (arm[...,2:3] if arm is not None and arm.shape[2]>=3 else np.zeros(shape,np.float32))
                ao = get('ao')
                ao = ao[...,:1] if ao is not None else (arm[...,:1] if arm is not None else None)
                normal = get('nor_dx')
                if normal is None:
                    normal = get('nor_gl')
                    if normal is not None:
                        normal = rgb(normal).copy(); normal[...,1] = 1-normal[...,1]; note('  OpenGL normal converted to DirectX (-Y).')
                if normal is None:
                    normal = get('normal')
                    if normal is not None:
                        normal = rgb(normal).copy()
                        note('  Unlabelled normal interpreted as '+normal_format+' (selected setting).')
                        if normal_format == 'OpenGL':
                            normal[...,1] = 1-normal[...,1]
                            note('  OpenGL normal converted to DirectX (-Y).')
                if normal is None:
                    normal = np.empty(shape[:-1]+(3,),np.float32); normal[:] = [.5,.5,1]; note('  Missing normals: flat normal used.')
                normal = rgb(normal)
                normal = np.concatenate((normal,1-rough),axis=2)
                spec = get('spec',True)
                if spec is None:
                    spec = srgb(.04*(1-metal) + linear(base)*metal)
                    note('  Metallic/base colour converted to specular reflectance (dielectric F0 = 0.04).')
                else: spec = rgb(spec)
                diffuse = srgb(linear(base)*(1-metal))
                if bake_ao and ao is not None:
                    diffuse = srgb(linear(diffuse)*ao); note('  AO baked into diffuse.')
                opacity = get('opacity')
                if opacity is not None: diffuse = np.concatenate((diffuse,opacity[...,:1]),axis=2)
                textures = [('diff',diffuse,'AlbedoWithOpacity' if opacity is not None else 'Albedo','Diffuse'),('ddna',normal,'NormalsWithSmoothness','Bumpmap'),('spec',spec,'Reflectance','Specular')]
                disp = get('disp')
                if disp is not None:
                    d = disp[...,:1]; textures.append(('displ',np.repeat(d,4,axis=2),'Displacement','Heightmap'))
                    note('  Height map prepared; enable POM/tessellation manually if needed.')
                emission = get('emission',True)
                if emission is not None: textures.append(('em',rgb(emission),'Albedo','Emittance'))
                if ao is not None:
                    save_tif(folder/(name+'_ao.tif'),np.repeat(ao,3,axis=2),'ReferenceImage_Linear')
                    note('  AO retained as an auxiliary TIFF (Illum has no standalone AO slot).')
                scattering = get('scattering')
                if scattering is not None:
                    save_tif(folder/(name+'_scattering.tif'),rgb(scattering),'ReferenceImage_Linear')
                    note('  Scattering retained as an auxiliary TIFF; subsurface scattering requires manual shader setup.')
                root = ET.Element('Material', {'Name':name,'MtlFlags':'524416','Shader':'Illum','GenMask':'0','StringGenMask':'%NORMAL_MAP%SPECULAR_MAP','SurfaceType':'','MatTemplate':'','Diffuse':'1,1,1','Specular':'1,1,1','Opacity':'1','Shininess':'255','vertModifType':'0','LayerAct':'1'})
                tx = ET.SubElement(root,'Textures')
                for tail, array, preset, slot in textures:
                    p = folder/(name+'_'+tail+'.tif')
                    save_tif(p,array,preset)
                    if compile_dds:
                        note('  Compiling ' + p.name)
                        cmd = [str(rc),str(p),'/preset='+preset,'/p=pc','/userdialog=0','/refresh=1','/threads=2','/logprefix='+str(folder/('rc_'+tail+'_'))]
                        proc = subprocess.run(cmd,cwd=str(Path(rc).parent),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=600)
                        (folder/('rc_'+tail+'_console.log')).write_bytes(proc.stdout)
                        dds = p.with_suffix('.dds')
                        if proc.returncode != 0 or not dds.is_file() or dds.read_bytes()[:4] != b'DDS ':
                            raise RuntimeError('DDS compilation failed for '+p.name+'. See rc_'+tail+'_console.log in '+str(folder))
                    ET.SubElement(tx,'Texture',{'Map':slot,'File':'./'+p.with_suffix('.dds' if compile_dds else '.tif').name})
                ET.SubElement(root,'PublicParams',{'EmittanceMapGamma':'1','Emittance':'1,1,1,1' if emission is not None else '0,0,0,0'})
                ET.indent(root)
                ET.ElementTree(root).write(folder/(name+'.mtl'),encoding='utf-8',xml_declaration=True)
                if 'glass' in name.split('_'):
                    note('  Glass material: textures prepared; transparency/refraction require the Glass shader. See GLASS_SETUP.txt.')
                    (folder/'GLASS_SETUP.txt').write_text(
                        'The generated .mtl is an opaque Illum texture-material starting point.\n'
                        'To use this texture set as glass, change its Shader to Glass in Material Editor.\n'
                        'Keep the converted _ddna texture in the Bumpmap slot.\n'
                        'Adjust Tint Cloudiness for a cloudy/frosted appearance, and Bump Map Scale for distortion.\n'
                        'Set up Environment Map reflections with a suitable cubemap for your level.\n'
                        'Base colour/roughness maps do not define transparency, refraction or physical glass thickness.\n'
                        'No opacity map was inferred from base colour, AO or height. Tune the glass in your scene.\n'
                        'https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756816/pages/29448946\n',encoding='utf-8')
                report = {'source':str(zip_path),'material':name,'size':size,'compiled_dds':compile_dds,'unlabelled_normal_format':normal_format,'selected_maps':{k:v[1].filename for k,v in maps.items()},'notes':messages}
                (folder/'conversion.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                (folder/'IMPORT.txt').write_text('Copy this entire folder anywhere under your CRYENGINE project Assets folder.\nOpen the .mtl in Material Editor and assign it to an object. Texture paths are material-relative.\nKeep the DDS sidecars, including .dds.a and numbered streaming mip files.\nHeight/POM, opacity and emission may require shader feature adjustments in Material Editor.\n',encoding='utf-8')
                note('Finished: ' + str(folder)); results.append(folder)
            except Exception:
                (folder/'FAILED.txt').write_text(traceback.format_exc(),encoding='utf-8')
                raise
    return results

def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk(); root.title(APP); root.geometry('800x690'); root.minsize(700,610)
    style = ttk.Style(); style.theme_use('clam')
    style.configure('TButton',padding=7); style.configure('TLabel',font=('Segoe UI',10))
    body = ttk.Frame(root,padding=22); body.pack(fill='both',expand=True); body.columnconfigure(1,weight=1)
    ttk.Label(body,text=APP,font=('Segoe UI',19,'bold')).grid(row=0,column=0,columnspan=3,sticky='w')
    ttk.Label(body,text='Poly Haven, TextureCan and 3DTextures.me ZIPs. Missing maps are handled automatically.').grid(row=1,column=0,columnspan=3,sticky='w',pady=(5,18))
    home = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    zipvar=tk.StringVar(); outvar=tk.StringVar(value=str(home/'Converted')); rcvar=tk.StringVar(value=RC_DEFAULT)
    compilevar=tk.BooleanVar(value=True); aovar=tk.BooleanVar(value=False); sizevar=tk.StringVar(value='4096')
    normalvar=tk.StringVar(value='OpenGL')
    events=queue.Queue(); busy=False; last=[]
    def pick_zip():
        p=filedialog.askopenfilename(title='Material texture ZIP',filetypes=[('ZIP archives','*.zip')])
        if p:
            zipvar.set(p)
            try:
                g=scan(p); status.set('Detected: '+ '; '.join(n+' ('+', '.join(m)+')' for n,m in g.items()))
            except Exception as e: messagebox.showerror(APP,str(e))
    for row,label,var,action in [(2,'Downloaded ZIP',zipvar,pick_zip),(3,'Output folder',outvar,lambda: outvar.set(filedialog.askdirectory() or outvar.get())),(4,'CRYENGINE rc.exe',rcvar,lambda: rcvar.set(filedialog.askopenfilename(filetypes=[('Resource Compiler','rc.exe')]) or rcvar.get()))]:
        ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',pady=7,padx=(0,12))
        ttk.Entry(body,textvariable=var).grid(row=row,column=1,sticky='ew',padx=(0,8))
        ttk.Button(body,text='Browse…',command=action).grid(row=row,column=2)
    opts=ttk.Frame(body); opts.grid(row=5,column=0,columnspan=3,sticky='w',pady=12)
    ttk.Checkbutton(opts,text='Compile DDS with CRYENGINE',variable=compilevar).pack(side='left')
    ttk.Checkbutton(opts,text='Bake AO into diffuse',variable=aovar).pack(side='left',padx=15)
    ttk.Label(opts,text='Max size').pack(side='left',padx=(0,5))
    ttk.Combobox(opts,textvariable=sizevar,values=['1024','2048','4096','8192','Original'],width=9,state='readonly').pack(side='left')
    normals=ttk.Frame(body); normals.grid(row=6,column=0,columnspan=3,sticky='w',pady=(0,10))
    ttk.Label(normals,text='Unlabelled normal maps:').pack(side='left',padx=(0,8))
    ttk.Combobox(normals,textvariable=normalvar,values=['OpenGL','DirectX'],width=9,state='readonly').pack(side='left')
    ttk.Label(normals,text='  Explicit DX / GL filenames take priority.',foreground='#555555').pack(side='left')
    ttk.Label(body,text='Creates a new folder per material; existing conversions are kept.\nPNG, JPG, TIFF and EXR supported. Blender / glTF files are ignored.',foreground='#555555').grid(row=7,column=0,columnspan=3,sticky='w')
    status=tk.StringVar(value='Ready — select a ZIP to begin.')
    ttk.Label(body,textvariable=status,wraplength=720).grid(row=8,column=0,columnspan=3,sticky='w',pady=(15,8))
    bar=ttk.Progressbar(body,mode='indeterminate'); bar.grid(row=9,column=0,columnspan=3,sticky='ew')
    text=tk.Text(body,height=12,wrap='word',font=('Consolas',9),state='disabled'); text.grid(row=10,column=0,columnspan=3,sticky='nsew',pady=10); body.rowconfigure(10,weight=1)
    buttons=ttk.Frame(body); buttons.grid(row=11,column=0,columnspan=3,sticky='e')
    def append(s):
        text.configure(state='normal'); text.insert('end',s+'\n'); text.see('end'); text.configure(state='disabled')
    def start():
        nonlocal busy
        if busy: return
        if not Path(zipvar.get()).is_file(): messagebox.showerror(APP,'Choose an existing ZIP file.'); return
        if not outvar.get().strip(): messagebox.showerror(APP,'Choose an output folder.'); return
        args=(zipvar.get(),outvar.get(),rcvar.get(),compilevar.get(),0 if sizevar.get()=='Original' else int(sizevar.get()),aovar.get())
        chosen_normal_format=normalvar.get()
        busy=True; convertbtn.configure(state='disabled'); bar.start(); status.set('Converting — this may take a few minutes.')
        def work():
            try: events.put(('done',convert(*args,log=lambda s:events.put(('log',s)),normal_format=chosen_normal_format)))
            except Exception as e: events.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()
    def poll():
        nonlocal busy,last
        try:
            while True:
                kind,value=events.get_nowait()
                if kind=='log': append(value)
                else:
                    busy=False; bar.stop(); convertbtn.configure(state='normal')
                    if kind=='done': last=value; status.set('Complete — '+str(len(value))+' material(s) ready.'); append('Copy the converted material folder into your project Assets folder.')
                    else: status.set('Conversion failed — see details below.'); append(value); messagebox.showerror(APP,value)
        except queue.Empty: pass
        root.after(100,poll)
    def open_output():
        p=last[-1] if last else Path(outvar.get())
        if p.is_dir(): os.startfile(p)
    ttk.Button(buttons,text='Open output folder',command=open_output).pack(side='left',padx=8)
    convertbtn=ttk.Button(buttons,text='Convert material',command=start); convertbtn.pack(side='left')
    def close():
        if busy: messagebox.showinfo(APP,'Please wait for the current conversion to finish.'); return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close); poll(); root.mainloop()

if __name__ == '__main__':
    if '--convert' in sys.argv:
        p=argparse.ArgumentParser(); p.add_argument('--convert'); p.add_argument('--output',required=True); p.add_argument('--rc',default=RC_DEFAULT); p.add_argument('--no-dds',action='store_true'); p.add_argument('--max-size',type=int,default=4096); p.add_argument('--normal-format',choices=['OpenGL','DirectX'],default='OpenGL')
        a=p.parse_args()
        try:
            result=convert(a.convert,a.output,a.rc,not a.no_dds,a.max_size,normal_format=a.normal_format)
            (Path(a.output)/'last-result.json').write_text(json.dumps([str(x) for x in result]))
        except Exception:
            Path(a.output).mkdir(parents=True,exist_ok=True)
            (Path(a.output)/'last-error.txt').write_text(traceback.format_exc()); sys.exit(1)
    else:
        gui()

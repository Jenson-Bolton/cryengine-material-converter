# CRYENGINE Material Converter

[![Build and release](https://github.com/Jenson-Bolton/cryengine-material-converter/actions/workflows/build-release.yml/badge.svg)](https://github.com/Jenson-Bolton/cryengine-material-converter/actions/workflows/build-release.yml)

**[Download the latest Windows release](https://github.com/Jenson-Bolton/cryengine-material-converter/releases/latest)**

A simple Windows GUI that converts downloaded PBR texture ZIPs into CRYENGINE material files, 16-bit source TIFFs and compiled DDS textures.

Supports the texture naming used by **Poly Haven**, **TextureCan** and **3DTextures.me**. You do not need to download every map or extract the ZIP first.

## Requirements

- Windows 10/11, 64-bit.
- A CRYENGINE installation with `Tools/rc/rc.exe` for DDS compilation. Tested with **CRYENGINE 5.7.1**.
- The standalone EXE includes Python and the image libraries. Users of the EXE do not need Python installed.

CRYENGINE and its Resource Compiler are not included. The tool looks for an adjacent engine or common `C:\CRYENGINE\Engines` / `D:\CRYENGINE\Engines` installations. You can browse to `rc.exe` in the GUI, or set the `CRYENGINE_RC` environment variable.

## Use the app

1. Run **MaterialConverter.exe**.
2. Browse to a downloaded texture ZIP.
3. Choose an output folder. The default is `Converted` beside the EXE.
4. Leave **Compile DDS with CRYENGINE** enabled and check the Resource Compiler path.
5. For filenames ending in `_normal`, select their normal-map format. The default is **OpenGL**; explicit DX/GL filenames always take priority. The format of an unlabelled map cannot be determined from its filename.
6. Click **Convert material**.
7. Copy the entire generated material folder anywhere inside your project's **Assets** folder, then open its `.mtl` in Material Editor and assign it to an object.

Keep the complete folder, including DDS metadata and any attached/streaming mip files. Texture paths are relative to the `.mtl`, so the folder can be moved within Assets.

Existing conversions are preserved: subsequent runs use folders ending in `_2`, `_3`, etc. Multiple materials in one ZIP get separate folders. `conversion.json` records the maps selected and assumptions made; `rc_*` files contain compiler logs. A failure leaves `FAILED.txt` with diagnostic details.

## Supported texture names

PNG, JPG/JPEG, TIFF, EXR, BMP and TGA are supported. Map names are case-insensitive and use an underscore before the map role. A resolution suffix such as `_2k` is optional. Nested ZIP folders are supported.

| Map | Recognised suffixes |
| --- | --- |
| Base colour | `diff`, `albedo`, `basecolor`, `color`, `colour` |
| DirectX normal | `nor_dx`, `normal_dx`, `normal_directx` |
| OpenGL normal | `nor_gl`, `normal_gl`, `normal_opengl` |
| Unlabelled normal | `normal` — uses the GUI/CLI normal-format setting |
| Roughness | `rough`, `roughness` |
| Packed AO/roughness/metallic | `arm` — R/G/B respectively |
| Ambient occlusion | `ao`, `ambientOcclusion`, `ambient_occlusion` |
| Height | `disp`, `displacement`, `height` |
| Metallic | `metal`, `metallic`, `metalness` |
| Specular | `spec`, `specular` |
| Opacity | `opacity`, `alpha` |
| Emission | `emission`, `emissive` |
| Auxiliary scattering | `scattering` |

Examples: `white_stucco_diff_2k.png`, `fabric_0012_normal_directx_2k.png`, `Glass_Frosted_001_ambientOcclusion.jpg`.

Separate maps take priority over ARM channels. Explicit DirectX normals take priority over explicit OpenGL normals, which take priority over unlabelled normals. Within one role the highest named resolution is preferred; format priority is PNG, EXR, TIFF, TGA, BMP, then JPEG. Duplicate ZIP entries are handled. Mac `__MACOSX` / `._` metadata, preview images without a recognised map suffix, Blender, glTF and MaterialX files are ignored.

## Conversion details

- Creates an **Illum** material using CRYENGINE's specular/smoothness workflow.
- Packs normal RGB and `1 - roughness` in the alpha channel of `_ddna.tif`.
- Converts OpenGL normals to DirectX by flipping the green channel.
- Converts metallic/base colour into diffuse and specular reflectance using dielectric F0 = 0.04, unless an explicit specular map is supplied.
- Treats EXR colour maps as linear and ordinary colour images as sRGB. Data maps are treated as linear.
- Writes 16-bit TIFFs with embedded CryTIF preset metadata. The installed Resource Compiler generates DDS compression and mipmaps.
- Missing maps use a grey diffuse, flat normal, roughness 0.5 and non-metal defaults.
- Retains AO separately. **Bake AO into diffuse** is optional and off by default.
- Packs height into the displacement texture's alpha and assigns it to Heightmap.
- Retains scattering separately for manual subsurface setup.
- Limits the longest dimension to 4096 by default, without enlarging smaller inputs. All maps for a material are resized to a common size. Other limits and **Original** are selectable.

## Glass and other special materials

The ZIP contains texture maps, not a complete CRYENGINE shader configuration. The generated material starts with **opaque Illum**. To make transparent or frosted glass, choose the **Glass** shader in Material Editor and tune its cloudiness, normal scale, refraction and reflections for your scene. Materials with `glass` in their name also receive `GLASS_SETUP.txt`.

The converter does not infer opacity from base colour, height or AO. Height/POM/tessellation, emission strength and subsurface scattering can require manual shader setup. It does not import meshes, infer physical size, or execute files contained in an archive.

Input limits are 70 megapixels, 16 channels and 2 GB of uncompressed data per image. Very large images require substantial RAM. Each Resource Compiler step has a 10-minute timeout. The EXE needs write access to the selected output folder.

## Run from source

Use **Python 3.13, 64-bit on Windows**. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\converter.py
```

For command-line conversion:

```powershell
.\.venv\Scripts\python.exe src\converter.py --convert "C:\Downloads\material.zip" --output "C:\Materials\Converted" --rc "C:\CRYENGINE\Tools\rc\rc.exe"
```

Optional arguments: `--max-size 2048`, `--max-size 0` (original dimensions), `--no-dds`, and `--normal-format DirectX` (or `OpenGL`). A failed conversion returns exit code 1; successful conversions return 0. CLI result/error files are written in the output folder.

## Test and build the Windows EXE

```powershell
.\build.ps1
```

The build script creates a local `.venv`, installs pinned dependencies, runs the synthetic regression checks, builds `dist\MaterialConverter.exe` with PyInstaller, and collects the dependency licence notices. Use `-SkipInstall` to reuse an already prepared environment. You can supply `-PythonExecutable "C:\path\to\venv\Scripts\python.exe"` to use another environment.

To run just the regression checks:

```powershell
.\.venv\Scripts\python.exe tests\test_converter.py
```

Tests cover map aliases, partial downloads, ARM packing, normal conventions and overrides, 16-bit TIFF output, EXR colour conversion, ignored metadata/previews, duplicate conversion folders and clear failure on an unsupported archive. Fixtures are generated locally; no texture downloads or CRYENGINE installation are required for these checks. DDS compilation was additionally tested with the 5.7.1 compiler and the three providers' sample ZIPs; synthetic checks do not render a material in Sandbox.

## Put this on GitHub

The public repository is [Jenson-Bolton/cryengine-material-converter](https://github.com/Jenson-Bolton/cryengine-material-converter). A `.gitignore` excludes build environments, EXEs, archives and generated materials.

Keep downloaded textures and your game assets out of the source repository unless you have separately checked their redistribution terms. No sample downloads, engine binaries, personal paths or credentials are included in this source package.

## Automated builds and releases

Every push to **`main`** automatically:

1. Installs Python 3.13 and the pinned dependencies on a Windows runner.
2. Runs the conversion regression checks and builds the standalone EXE.
3. Runs a conversion through the actual packaged EXE, without CRYENGINE.
4. Packages the EXE, README, licence and dependency notices into `MaterialConverter-Windows.zip`, with `SHA256SUMS.txt`.
5. Publishes a GitHub Release tagged `build-<run number>-<short commit>` and attaches both files.

Pull requests to `main` run the same tests/build and retain downloadable workflow artifacts, but do not publish releases. The **Actions → Build and release Windows app → Run workflow** button can also build manually; selecting `main` publishes a release. Re-running a run reuses its tag and refreshes its release files.

No personal access token or extra repository secret is required: the publishing job uses GitHub's built-in token with `contents: write`. Build jobs use read-only repository access, and action revisions are pinned. Each successful `main` push gets a new tag, so you do not need to edit a version number. Builds that fail tests or packaging do not publish a release.

GitHub runners do not have your CRYENGINE installation, so CI verifies source conversion and the frozen app; it cannot verify the proprietary DDS compiler or rendered shader appearance. Those still need testing with your local engine.

## Licence and acknowledgements

The converter source is licensed under **MIT**; see [LICENSE](LICENSE). Dependencies retain their own licences; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). CRYENGINE is a separate product subject to Crytek's terms. This is an independent utility and is not affiliated with Crytek or the texture providers.

References: [CryTIF export and presets](https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756816/pages/23308299), [material-relative texture paths](https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756816/pages/29799264), [Glass shader](https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756816/pages/29448946), [Poly Haven map conventions](https://docs.polyhaven.com/en/technical-standards/textures).

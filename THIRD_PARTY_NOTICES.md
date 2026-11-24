# Third-party notices

The MIT licence in this repository covers the converter's original source code. Python, Tcl/Tk, NumPy, Pillow, OpenImageIO, tifffile and the PyInstaller bootloader retain their respective licences.

The `build.ps1` script collects the licence, copyright and notice files supplied by the installed dependencies into `dist/licenses`. Preserve those files when distributing a built EXE. OpenImageIO's Windows wheel and NumPy's wheel also contain native libraries; retain their supplied notices. PyInstaller's licence includes a bootloader exception for applications it packages; its licence text is included in the collected notices.

CRYENGINE's Resource Compiler and engine libraries are **not bundled**. Users must supply an installed CRYENGINE distribution. Texture downloads are also not part of this repository; their licences are independent of the converter's licence.

"""Build the desktop review edition using PyInstaller."""

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parent.parent
    output = root / "desktop" / "dist"
    work = root / "desktop" / "build"
    separator = os.pathsep
    platform_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--noupx", "--name", "VisionInspect", "--distpath", str(output), "--workpath", str(work), "--specpath", str(root / "desktop"), "--paths", str(root / "VisionInspect"), "--collect-data", "imgui_bundle", "--collect-binaries", "imgui_bundle", "--add-data", f"{root / 'VisionInspect' / 'examples'}{separator}examples"]
    for module in ("PySide6", "PyQt6", "PyQt5", "torch", "torchvision", "ultralytics", "matplotlib", "pandas", "scipy", "cv2", "IPython", "notebook", "jupyterlab", "pytest", "pyodide", "js"):
        command.extend(("--exclude-module", module))
    command.append(str(root / "desktop" / "entry.py"))
    subprocess.run(command, cwd=root, check=True)
    folder = output / "VisionInspect"
    executable = "VisionInspect.exe" if sys.platform == "win32" else "VisionInspect"
    (folder / "README.txt").write_text(f"VisionInspect desktop review edition ({platform_name})\n\nRun {executable}. Keep the _internal directory beside it.\nIncludes image review, drawing, undo, defect links, statistics and Excel export.\nYOLO/Torch inference is not included in this edition.\nConfiguration and logs are stored in the platform user data directory.\n", encoding="utf-8")
    files = [path for path in folder.rglob("*") if path.is_file()]
    archive_path = output / f"VisionInspect-{platform_name}-review.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(output).as_posix())
    sizes = {"platform": platform_name, "directory_bytes": sum(path.stat().st_size for path in files), "executable_bytes": (folder / executable).stat().st_size, "zip_bytes": archive_path.stat().st_size, "files": len(files)}
    (output / "sizes.json").write_text(json.dumps(sizes, indent=2), encoding="utf-8")
    print(json.dumps(sizes, indent=2), flush=True)


if __name__ == "__main__":
    main()

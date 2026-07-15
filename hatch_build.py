"""Custom hatchling build hook to copy platform-specific binaries into wheel."""
import os
import platform
import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        super().initialize(version, build_data)
        build_data['pure_python'] = False
        tag = self.config.get('tag')
        if tag:
            build_data['tag'] = tag
        else:
            build_data['infer_tag'] = True

        root = Path(self.root)
        system = platform.system()

        if system == "Darwin":
            vendor = root / "vendor" / "osx"
            platform_tag = "osx-x64"
        elif system == "Linux":
            vendor = root / "vendor" / "linux"
            platform_tag = "linux-x64"
        else:
            self.app.display_warning(f"Unsupported platform: {system}, skipping binary packaging")
            return

        pkg_dir = root / "sliver"

        minisat_bin = vendor / "minisat" / "minisat"
        if minisat_bin.exists():
            dest = pkg_dir / "minisat"
            dest.mkdir(exist_ok=True)
            shutil.copy2(minisat_bin, dest / "minisat")
            (dest / "minisat").chmod(0o755)
            minisat_license = vendor / "minisat" / "LICENSE"
            if minisat_license.exists():
                shutil.copy2(minisat_license, dest / "LICENSE")

        cbmc_dir = vendor / "cbmc"
        if cbmc_dir.exists():
            dest = pkg_dir / "cbmc"
            dest.mkdir(exist_ok=True)
            for f in cbmc_dir.iterdir():
                if f.name.startswith(".") or f.is_dir():
                    continue
                shutil.copy2(f, dest / f.name)
            for name in ("cbmc-simulator", "cbmc-5-74"):
                binpath = dest / name
                if binpath.exists():
                    binpath.chmod(0o755)

        dest = pkg_dir / "labs"
        dest.mkdir(exist_ok=True)
        labs_link = dest / "LabsTranslate"
        for candidate in [
            root / "build" / platform_tag / "sliver" / "labs" / "LabsTranslate",
            root / "labs" / "LabsTranslate" / "bin",
        ]:
            if candidate.is_file():
                if not labs_link.exists():
                    rel = os.path.relpath(candidate, labs_link.parent)
                    try:
                        os.symlink(rel, labs_link)
                    except OSError:
                        shutil.copy2(candidate, labs_link)
                        labs_link.chmod(0o755)
                break

        templates_link = pkg_dir / "labs" / "templates"
        templates_src = root / "labs" / "LabsTranslate" / "templates"
        if not templates_link.exists():
            try:
                os.symlink("../../labs/LabsTranslate/templates", templates_link)
            except OSError:
                if templates_src.exists():
                    shutil.copytree(templates_src, templates_link,
                                    ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))



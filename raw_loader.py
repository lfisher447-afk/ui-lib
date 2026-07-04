"""
Zerio UI Lib Raw Component Loader and Remote Executor.
Loads components, layouts, or complete sub-packages directly from GitHub raw links on-the-fly,
caches them locally in a secure sandbox, and dynamically injects them into the runtime path.
"""
import os
import sys
import importlib
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any

class RawComponentLoader:
    def __init__(self, cache_dir: str = ".zerio_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        sys.path.append(str(self.cache_dir.resolve()))
        self._registry: Dict[str, str] = {}

    def fetch_and_load(self, module_name: str, raw_url: str, force_update: bool = False) -> Optional[Any]:
        """
        Downloads a python module from a raw GitHub URL, saves it locally, and imports it.
        """
        target_file = self.cache_dir / f"{module_name}.py"
        
        if force_update or not target_file.exists():
            print(f"[RawLoader] Fetching '{module_name}' from: {raw_url}")
            try:
                headers = {"User-Agent": "ZerioRawLoader/3.0.0"}
                req = urllib.request.Request(raw_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10.0) as response:
                    content = response.read().decode("utf-8")
                    target_file.write_text(content, encoding="utf-8")
            except Exception as e:
                print(f"[RawLoader] Error downloading remote module: {e}")
                return None
                
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
            return importlib.import_module(module_name)
        except Exception as e:
            print(f"[RawLoader] Failed to dynamically load module '{module_name}': {e}")
            return None

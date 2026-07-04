"""
Zerio UI Lib Raw Component Loader and Remote Executor (Python Loadstring Engine).
Loads components, layouts, or complete sub-packages directly from GitHub raw links on-the-fly,
caches them locally in a secure sandbox, and dynamically injects them into the runtime path.
Includes a direct Lua-like loadstring wrapper and integrated remote auto-update checks.
"""
import os
import sys
import json
import time
import importlib
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, Union

class RawComponentLoader:
    def __init__(self, cache_dir: str = ".zerio_cache", ttl_seconds: int = 300):
        """
        Initializes the dynamic component loader.
        :param cache_dir: Sandbox folder where files are cached.
        :param ttl_seconds: Time-to-live for cache. After this, remote is checked for updates. Default 5 mins.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        sys.path.append(str(self.cache_dir.resolve()))
        self.ttl = ttl_seconds
        
        # Load or initialize version tracking registry
        self.registry_file = self.cache_dir / "loader_registry.json"
        self.registry: Dict[str, Dict[str, Any]] = {}
        self._load_registry()
        self._checked_updates = False

    def _load_registry(self):
        if self.registry_file.exists():
            try:
                self.registry = json.loads(self.registry_file.read_text(encoding="utf-8"))
            except Exception:
                self.registry = {}

    def _save_registry(self):
        try:
            self.registry_file.write_text(json.dumps(self.registry, indent=4), encoding="utf-8")
        except Exception as e:
            sys.stderr.write(f"[RawLoader] Failed to write registry: {e}\n")

    def check_for_library_updates(self, raw_url: str):
        """
        Queries the remote version.json from the repository root to detect if a new Python update is available.
        Prompts the user to update their Python application if a newer version is found.
        """
        try:
            if "raw.githubusercontent.com" in raw_url:
                parts = raw_url.split("/")
                base_parts = parts[:6]
                repo_root = "/".join(base_parts)
                version_url = f"{repo_root}/version.json"
            else:
                version_url = raw_url.rsplit("/", 1)[0] + "/version.json"

            print(f"[RawLoader] Checking for remote version updates from: {version_url}")
            req = urllib.request.Request(version_url, headers={"User-Agent": "ZerioRawLoader/3.0.0"})
            with urllib.request.urlopen(req, timeout=5.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                remote_version = data.get("version", "1.23")
                local_version = "1.22"
                
                try:
                    v_remote = float(remote_version)
                    v_local = float(local_version)
                    is_newer = v_remote > v_local
                except ValueError:
                    is_newer = remote_version != local_version

                if is_newer:
                    changelog_text = "\n".join([f"  - {change}" for change in data.get("changelog", [])])
                    print("\n" + "="*80)
                    print(f" [UPDATE AVAILABLE] A newer version of the Python suite is available!")
                    print(f" Current Version: {local_version}")
                    print(f" New Version:     {remote_version}")
                    if changelog_text:
                        print(f" Changelog:\n{changelog_text}")
                    print(" Please update your Python loader file to utilize the latest features.")
                    print("="*80 + "\n")
                    
                    sys.stdout.write(f"\n>>> There is a new version ({remote_version}) of Zerio Python. Press ENTER to acknowledge... ")
                    sys.stdout.flush()
                else:
                    print(f"[RawLoader] Version check complete. Running latest version ({local_version}).")
        except Exception as e:
            print(f"[RawLoader] Version check skipped/unavailable: {e}")

    def fetch_and_load(self, module_name: str, raw_url: str, force_update: bool = False) -> Optional[Any]:
        """
        Downloads a Python module from a raw GitHub URL, saves it locally, and imports it.
        Includes auto-update detection (checks remote timestamp/ETag if cached file exceeds TTL).
        """
        if not self._checked_updates:
            self.check_for_library_updates(raw_url)
            self._checked_updates = True

        target_file = self.cache_dir / f"{module_name}.py"
        now = time.time()
        
        # Check if we should update
        should_download = force_update or not target_file.exists()
        
        if not should_download and module_name in self.registry:
            meta = self.registry[module_name]
            last_checked = meta.get("last_checked", 0)
            if now - last_checked > self.ttl:
                # Cache expired, check remote headers to see if file changed
                print(f"[RawLoader] Cache TTL expired for '{module_name}'. Checking remote for auto-updates...")
                should_download = self._check_remote_for_update(module_name, raw_url)
        
        if should_download:
            print(f"[RawLoader] Downloading/updating '{module_name}' from: {raw_url}")
            success = self._download_file(module_name, raw_url)
            if not success and not target_file.exists():
                return None
        else:
            print(f"[RawLoader] Using cached, up-to-date version of '{module_name}'.")

        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
            return importlib.import_module(module_name)
        except Exception as e:
            print(f"[RawLoader] Failed to dynamically load module '{module_name}': {e}")
            return None

    def _check_remote_for_update(self, module_name: str, raw_url: str) -> bool:
        """
        Queries GitHub Raw server using a HEAD request to check ETag or Last-Modified headers.
        If changed, returns True to trigger download.
        """
        meta = self.registry.get(module_name, {})
        cached_etag = meta.get("etag")
        cached_modified = meta.get("last_modified")
        
        try:
            req = urllib.request.Request(raw_url, method="HEAD")
            req.add_header("User-Agent", "ZerioRawLoader/3.0.0")
            if cached_etag:
                req.add_header("If-None-Match", cached_etag)
            if cached_modified:
                req.add_header("If-Modified-Since", cached_modified)
                
            with urllib.request.urlopen(req, timeout=5.0) as response:
                # If we get a 200, check headers
                new_etag = response.headers.get("ETag")
                new_modified = response.headers.get("Last-Modified")
                
                # Update check metadata
                self.registry[module_name] = {
                    "etag": new_etag,
                    "last_modified": new_modified,
                    "last_checked": time.time()
                }
                self._save_registry()
                
                if new_etag and new_etag != cached_etag:
                    return True
                if new_modified and new_modified != cached_modified:
                    return True
                return False
        except urllib.error.HTTPError as e:
            if e.code == 304:
                # 304 Not Modified!
                print(f"[RawLoader] Server returned 304: '{module_name}' is fully up-to-date.")
                if module_name in self.registry:
                    self.registry[module_name]["last_checked"] = time.time()
                    self._save_registry()
                return False
            print(f"[RawLoader] HTTP warning during update check: {e}")
            return True # Fallback to downloading on error
        except Exception as e:
            print(f"[RawLoader] Update check error: {e}")
            return True

    def _download_file(self, module_name: str, raw_url: str) -> bool:
        target_file = self.cache_dir / f"{module_name}.py"
        try:
            headers = {"User-Agent": "ZerioRawLoader/3.0.0"}
            # Add cache-busting timestamp on force updates to guarantee direct GitHub pull
            timestamp_url = f"{raw_url}?t={int(time.time())}"
            req = urllib.request.Request(timestamp_url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=10.0) as response:
                content = response.read().decode("utf-8")
                target_file.write_text(content, encoding="utf-8")
                
                # Save headers
                self.registry[module_name] = {
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "last_checked": time.time()
                }
                self._save_registry()
                print(f"[RawLoader] successfully synced and cached '{module_name}' (Auto-updates enabled).")
                return True
        except Exception as e:
            print(f"[RawLoader] Download error: {e}")
            return False


def loadstring(url: str, globals_dict: Optional[Dict[str, Any]] = None, cache_bypass: bool = False) -> Dict[str, Any]:
    """
    Downloads and executes remote Python code in a dictionary context, mimicking Lua's loadstring execution model.
    Usage:
        ui_lib = loadstring("https://raw.githubusercontent.com/lfisher447-afk/ui-lib/main/raw_loader.py")()
    """
    if globals_dict is None:
        globals_dict = {}
    
    # Ensure baseline imports are available in execution context
    globals_dict.setdefault("sys", sys)
    globals_dict.setdefault("os", os)
    globals_dict.setdefault("json", json)
    globals_dict.setdefault("time", time)
    
    try:
        url_with_cb = url
        if cache_bypass:
            url_with_cb = f"{url}?t={int(time.time())}"
            
        headers = {"User-Agent": "ZerioPythonLoadstring/3.0.0"}
        req = urllib.request.Request(url_with_cb, headers=headers)
        
        print(f"[Loadstring] Fetching raw execution script: {url}")
        with urllib.request.urlopen(req, timeout=10.0) as response:
            source_code = response.read().decode("utf-8")
            
        print(f"[Loadstring] Executing compiled AST sandbox...")
        # Compile source into bytecode to raise syntax errors early
        bytecode = compile(source_code, f"remote_loadstring:{url}", "exec")
        exec(bytecode, globals_dict)
        return globals_dict
    except Exception as e:
        sys.stderr.write(f"[Loadstring Error] Execution failed for remote script: {e}\n")
        raise e

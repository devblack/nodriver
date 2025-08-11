import logging
import os
import pathlib
import secrets
import sys
import tempfile
import zipfile
import asyncio
import json
from typing import List, Optional, Union
from functools import reduce

__all__ = [
    "Config",
    "find_chrome_executable",
    "temp_profile_dir",
    "is_root",
    "is_posix",
    "PathLike",
    "prefs_to_json",
    "write_prefs",
    "read_prefs"
]

logger = logging.getLogger(__name__)
is_posix = sys.platform.startswith(("darwin", "cygwin", "linux", "linux2"))

PathLike = Union[str, pathlib.Path]
AUTO = None

def prefs_to_json(dot_prefs: dict) -> dict:
    """Convert dot-separated keys into nested dictionaries"""
    def deep_merge(dict1, dict2):
        """Recursively merge two dictionaries"""
        result = dict1.copy()
        for key, value in dict2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def undot_key(key, value):
        if "." in key:
            key, rest = key.split(".", 1)
            value = undot_key(rest, value)
        return {key: value}
    
    result = {}
    for k, v in dot_prefs.items():
        nested_dict = undot_key(k, v)
        result = deep_merge(result, nested_dict)
    return result

def _sync_write_prefs(prefs: dict, path: str):
    """Synchronously write preferences to file"""
    with open(path, "w+", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)

async def write_prefs(prefs: dict, prefs_path: str):
    """Asynchronously write preferences to file"""
    loop = asyncio.get_running_loop()
    data = prefs_to_json(prefs)
    await loop.run_in_executor(None, _sync_write_prefs, data, prefs_path)

def _sync_read_prefs(path: str) -> dict:
    """Synchronously read preferences from file"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

async def read_prefs(prefs_path: str) -> dict:
    """Asynchronously read preferences from file"""
    loop = asyncio.get_running_loop()
    prefs = await loop.run_in_executor(None, _sync_read_prefs, prefs_path)
    return prefs

class Config:
    """
    Config object
    """

    def __init__(
        self,
        user_data_dir: Optional[PathLike] = AUTO,
        headless: Optional[bool] = False,
        browser_executable_path: Optional[PathLike] = AUTO,
        browser_args: Optional[List[str]] = AUTO,
        sandbox: Optional[bool] = True,
        lang: Optional[str] = "en-US",
        prefs: Optional[dict] = AUTO,
        host: str = AUTO,
        port: int = AUTO,
        expert: bool = AUTO,
        **kwargs: dict,
    ):
        """
        creates a config object.
        Can be called without any arguments to generate a best-practice config, which is recommended.

        calling the object, eg :  myconfig() , will return the list of arguments which
        are provided to the browser.

        additional arguments can be added using the :py:obj:`~add_argument method`

        Instances of this class are usually not instantiated by end users.

        :param user_data_dir: the data directory to use
        :param headless: set to True for headless mode
        :param browser_executable_path: specify browser executable, instead of using autodetect
        :param browser_args: forwarded to browser executable. eg : ["--some-chromeparam=somevalue", "some-other-param=someval"]
        :param sandbox: disables sandbox
        :param autodiscover_targets: use autodiscovery of targets
        :param lang: language string to use other than the default "en-US,en;q=0.9"
        :param prefs: preferences to apply to Chrome profile using dot notation keys. 
               eg: {"profile.default_content_setting_values.images": 2} to disable images
        :param expert: when set to True, enabled "expert" mode.
               This conveys, the inclusion of parameters: --disable-web-security ----disable-site-isolation-trials,
               as well as some scripts and patching useful for debugging (for example, ensuring shadow-root is always in "open" mode)

        :param kwargs:

        :type user_data_dir: PathLike
        :type headless: bool
        :type browser_executable_path: PathLike
        :type browser_args: list[str]
        :type sandbox: bool
        :type lang: str
        :type prefs: dict
        :type kwargs: dict
        """

        if not browser_args:
            browser_args = []

        if not user_data_dir:
            self._user_data_dir = temp_profile_dir()
            self._custom_data_dir = False
        else:
            self.user_data_dir = user_data_dir

        if not browser_executable_path:
            browser_executable_path = find_chrome_executable()

        self._browser_args = browser_args

        self.browser_executable_path = browser_executable_path
        self.headless = headless
        self.sandbox = sandbox
        self.host = host
        self.port = port
        self.expert = expert
        self._extensions = []
        # when using posix-ish operating system and running as root
        # you must use no_sandbox = True, which in case is corrected here
        if is_posix and is_root() and sandbox:
            logger.info("detected root usage, autoo disabling sandbox mode")
            self.sandbox = False

        self.autodiscover_targets = True
        self.lang = lang
        self.prefs = prefs if prefs is not AUTO else {}
        self._prefs_applied = False  # Track if preferences have been applied

        # other keyword args will be accessible by attribute
        self.__dict__.update(kwargs)
        super().__init__()
        self._default_browser_args = [
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-service-autorun",
            "--no-default-browser-check",
            "--homepage=about:blank",
            "--no-pings",
            "--password-store=basic",
            "--disable-infobars",
            "--disable-breakpad",
            "--disable-component-update",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-networking",
            "--disable-dev-shm-usage",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-session-crashed-bubble",
            "--disable-search-engine-choice-screen",
        ]

    @property
    def browser_args(self):
        return sorted(self._default_browser_args + self._browser_args)

    @property
    def user_data_dir(self):
        return self._user_data_dir

    @user_data_dir.setter
    def user_data_dir(self, path: PathLike):
        self._user_data_dir = str(path)
        self._custom_data_dir = True

    @property
    def uses_custom_data_dir(self) -> bool:
        return self._custom_data_dir

    def add_extension(self, extension_path: PathLike):
        """
        adds an extension to load, you could point extension_path
        to a folder (containing the manifest), or extension file (crx)

        :param extension_path:
        :type extension_path:
        :return:
        :rtype:
        """
        path = pathlib.Path(extension_path)

        if not path.exists():
            raise FileNotFoundError("could not find anything here: %s" % str(path))

        if path.is_file():
            tf = tempfile.mkdtemp(prefix=f"extension_", suffix=secrets.token_hex(4))
            with zipfile.ZipFile(path, "r") as z:
                z.extractall(tf)
                self._extensions.append(tf)

        elif path.is_dir():
            for item in path.rglob("manifest.*"):
                path = item.parent
            self._extensions.append(path)

    # def __getattr__(self, item):
    #     if item not in self.__dict__:

    def apply_prefs(self):
        """
        Apply preferences to the Chrome profile.
        This should be called after the user data directory is set up.
        """
        if not self.prefs or self._prefs_applied:
            return
        prefs_path = os.path.join(self.user_data_dir, "Default", "Preferences")
        prefs_dir = os.path.dirname(prefs_path)
        # Create Default directory if it doesn't exist
        os.makedirs(prefs_dir, exist_ok=True)
        try:
            # Read existing preferences if file exists
            if os.path.exists(prefs_path):
                existing_prefs = _sync_read_prefs(prefs_path)
            else:
                existing_prefs = {}
            # Update with new preferences
            existing_prefs.update(self.prefs)
            # Write preferences using the helper function
            data = prefs_to_json(existing_prefs)
            _sync_write_prefs(data, prefs_path)
            self._prefs_applied = True  # Mark as applied
            logger.info(f"Applied preferences to {prefs_path}")
        except Exception as e:
            logger.warning(f"Failed to apply preferences: {e}")

    def __call__(self):
        # Apply preferences before launching browser
        self.apply_prefs()
        # the host and port will be added when starting
        # the browser, as by the time it starts, the port
        # is probably already taken
        args = self._default_browser_args.copy()

        args += ["--user-data-dir=%s" % self.user_data_dir]
        args += ["--disable-features=IsolateOrigins,site-per-process"]
        args += ["--disable-session-crashed-bubble"]
        if self.expert:
            args += ["--disable-web-security", "--disable-site-isolation-trials"]
        if self._browser_args:
            args.extend([arg for arg in self._browser_args if arg not in args])
        if self.headless:
            args.append("--headless=new")
        if not self.sandbox:
            args.append("--no-sandbox")
        if self.host:
            args.append("--remote-debugging-host=%s" % self.host)
        if self.port:
            args.append("--remote-debugging-port=%s" % self.port)
        return args

    def add_argument(self, arg: str):
        if any(
            x in arg.lower()
            for x in [
                "headless",
                "data-dir",
                "data_dir",
                "no-sandbox",
                "no_sandbox",
                "lang",
            ]
        ):
            raise ValueError(
                '"%s" not allowed. please use one of the attributes of the Config object to set it'
                % arg
            )
        self._browser_args.append(arg)

    def __repr__(self):
        s = f"{self.__class__.__name__}"
        for k, v in ({**self.__dict__, **self.__class__.__dict__}).items():
            if k[0] == "_":
                continue
            if not v:
                continue
            if isinstance(v, property):
                v = getattr(self, k)
            if callable(v):
                continue
            s += f"\n\t{k} = {v}"
        return s

    #     d = self.__dict__.copy()
    #     d.pop("browser_args")
    #     d["browser_args"] = self()
    #     return d


def is_root():
    """
    helper function to determine if user trying to launch chrome
    under linux as root, which needs some alternative handling
    :return:
    :rtype:
    """
    import ctypes
    import os

    try:
        return os.getuid() == 0
    except AttributeError:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0


def temp_profile_dir():
    """generate a temp dir (path)"""
    path = os.path.normpath(tempfile.mkdtemp(prefix="uc_"))
    return path


def find_chrome_executable(return_all=False):
    """
    Finds the chrome, beta, canary, chromium executable
    and returns the disk path
    """
    candidates = []
    if is_posix:
        for item in os.environ.get("PATH").split(os.pathsep):
            for subitem in (
                "google-chrome",
                "chromium",
                "chromium-browser",
                "chrome",
                "google-chrome-stable",
            ):
                candidates.append(os.sep.join((item, subitem)))
        if "darwin" in sys.platform:
            candidates += [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]

    else:
        for item in map(
            os.environ.get,
            ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"),
        ):
            if item is not None:
                for subitem in (
                    "Google/Chrome/Application",
                    "Google/Chrome Beta/Application",
                    "Google/Chrome Canary/Application",
                ):
                    candidates.append(os.sep.join((item, subitem, "chrome.exe")))
    rv = []
    for candidate in candidates:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            logger.debug("%s is a valid candidate... " % candidate)
            rv.append(candidate)
        else:
            logger.debug(
                "%s is not a valid candidate because don't exist or not executable "
                % candidate
            )

    winner = None

    if return_all and rv:
        return rv

    if rv and len(rv) > 1:
        # assuming the shortest path wins
        winner = min(rv, key=lambda x: len(x))

    elif len(rv) == 1:
        winner = rv[0]

    if winner:
        return os.path.normpath(winner)

    raise FileNotFoundError(
        "could not find a valid chrome browser binary. please make sure chrome is installed."
        "or use the keyword argument 'browser_executable_path=/path/to/your/browser' "
    )

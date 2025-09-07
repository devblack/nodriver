import logging
import asyncio  # noqa: E402

logger = logging.getLogger("demo")
logging.basicConfig(format=u'[%(asctime)s]::%(levelname)s # %(message)s', level=logging.INFO)
try:
    import nodriver as uc
except (ModuleNotFoundError, ImportError):
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import nodriver as uc


from time import monotonic  # noqa: E402

class Timing:

    def __init__(self):
        self.start = None
        self.stop = None
        self.taken = None

    def __enter__(self):
        self.start = monotonic()
        return self

    def __exit__(self, *args, **kwargs):
        self.stop = monotonic()
        self.taken = self.stop - self.start
        print("taken:", self.taken, "seconds")


config = uc.Config()
config.force_cleanup = False  # force cleanup of the browser profile
config.prefs = {
    "profile.default_content_setting_values.images": 2,  # disable images
    "profile.default_content_setting_values.notifications": 2,  # disable notifications
    "profile.default_content_setting_values.popups": 2,  # disable popups
    "profile.default_content_setting_values.geolocation": 2, # disable geolocation
}


async def main():

    browser = await uc.start(prefs=config.prefs, headless=False, user_data_dir="C:/temp/test_profile")
    await browser.get('https://www.nowsecure.nl')

    await asyncio.sleep(15)  # wait for a while to see the result

if __name__ == "__main__":
    with Timing() as t:
        uc.loop().run_until_complete(main())
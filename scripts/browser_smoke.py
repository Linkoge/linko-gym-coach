"""Repeatable local UI/upload/playback check. Screenshots remain in ignored data/."""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--video", type=Path)
    choice.add_argument("--job")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    out = Settings.from_env().data_dir / "browser-review"
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                external.append(request.url)
                if not request.url.startswith(args.base_url + "/")
                else None
            ),
        )
        if args.video:
            page.goto(args.base_url)
            page.locator("#video").set_input_files(str(args.video.resolve()))
            page.locator("#upload-button").click()
            page.wait_for_url("**/jobs/*")
        else:
            page.goto(args.base_url + "/jobs/" + args.job)
        page.locator("#result-page").wait_for(state="visible", timeout=3_600_000)
        job_id = page.url.rsplit("/", 1)[-1]
        target = out / job_id
        target.mkdir(exist_ok=True)
        for mode in ("smoothed", "raw", "original"):
            page.select_option("#overlay-mode", mode)
            page.wait_for_function("() => document.querySelector('video').readyState >= 1")
            page.locator("video").evaluate("v => v.play()")
            page.wait_for_function("() => document.querySelector('video').currentTime > 0.2")
            page.locator("video").evaluate("v => {v.pause(); v.currentTime=0;}")
        page.select_option("#overlay-mode", "smoothed")
        page.wait_for_function("() => document.querySelector('video').readyState >= 2")
        # Eagerly load all gallery pictures before recording screenshots.
        page.locator("img").evaluate_all("imgs => imgs.forEach(img => img.loading='eager')")
        page.wait_for_function(
            "() => [...document.images].every(i => i.complete && i.naturalWidth)"
        )
        page.screenshot(path=target / "results.png", full_page=True)
        page.locator("#gallery").screenshot(path=target / "verification.png")
        count = page.locator(".gallery-item").count()
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.screenshot(path=target / "results-mobile.png", full_page=True)
        assert not errors, errors
        assert not external, external
        assert 1 <= count <= 10
        print(
            f"UI/playback checks passed; job {job_id}; {count} gallery frames; screenshots {target}"
        )
        browser.close()


if __name__ == "__main__":
    main()

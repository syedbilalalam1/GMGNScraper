from __future__ import annotations

import asyncio
import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import os

from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception
from playwright.async_api import async_playwright, Page
import random
import logging


GMGN_URL = "https://gmgn.ai/trade/uZy0WmVx?chain=sol"


@dataclass
class ScrapeResult:
    addresses: List[str]
    saved_csv: Optional[Path]


async def _get_copy_buttons(page: Page):
    # The copy button appears as an svg with specific classes; prefer a robust selector.
    # We'll look for elements with a title or aria-label containing 'copy' too, as a fallback.
    # First try: css by role button with name copy
    buttons = await page.locator("svg:has(path)").all()
    return buttons


async def _collect_addresses_by_copy(page: Page, expected_count: int = 100) -> List[str]:
    addresses: List[str] = []
    seen = set()

    # Ensure page is fully loaded and list rendered
    await page.wait_for_load_state("networkidle")

    # Scroll container to load more if it's virtualized
    last_height = 0
    for _ in range(50):
        await page.mouse.wheel(0, 800)
        await asyncio.sleep(0.2)

    # Try to find likely copy icons in rows; prefer buttons with copy-like attributes
    # We'll expand strategy: query icons inside rows and use page.evaluate to read adjacent text
    # However, gmgn.ai might copy to clipboard via JS, so we can listen to clipboard by invoking navigator.clipboard.readText

    # Enable clipboard read permission via context option when launching (set elsewhere)

    # Heuristic: click all visible copy icons and read clipboard after each click
    copy_icon_locator = page.locator(
        "[class*='cursor-pointer'] svg, svg.cursor-pointer, button[aria-label*='copy' i], [data-testid*='copy' i]"
    )

    count = await copy_icon_locator.count()
    if count == 0:
        # fallback: any svg inside rows that can be clicked
        copy_icon_locator = page.locator("svg")
        count = await copy_icon_locator.count()

    # To avoid clicking unrelated svgs, we'll iterate rows: find items containing 'sol' addresses (start with 'So'?)
    # Instead, we'll fallback to extracting the text content of probable address elements using regex
    import re
    text_content = await page.content()
    # Common Solana address pattern: base58 32-44 chars, excluding 0,O,I,l
    addr_pattern = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
    found = list(dict.fromkeys(addr_pattern.findall(text_content)))
    # Limit to expected_count if large
    if len(found) >= expected_count:
        return found[:expected_count]

    # If not enough found via HTML, try dynamic copy clicks as a secondary source
    for i in range(min(count, expected_count * 3)):
        try:
            el = copy_icon_locator.nth(i)
            if await el.is_visible():
                await el.click()
                # Give site time to set clipboard
                await asyncio.sleep(0.1)
                # Read clipboard from the page context
                try:
                    clip = await page.evaluate("navigator.clipboard.readText()")
                except Exception:
                    clip = ""
                if clip and clip not in seen and addr_pattern.fullmatch(clip):
                    addresses.append(clip)
                    seen.add(clip)
                if len(addresses) >= expected_count:
                    break
        except Exception:
            continue

    # Merge with found from static content
    for a in found:
        if a not in seen:
            addresses.append(a)
            seen.add(a)
        if len(addresses) >= expected_count:
            break

    return addresses


async def _try_dismiss_consent(page: Page):
    for selector in [
        "button:has-text('Accept')",
        "button:has-text('Agree')",
        "text=Accept All",
        "#onetrust-accept-btn-handler",
    ]:
        try:
            loc = page.locator(selector)
            if await loc.count() > 0:
                await loc.first.click(timeout=1500)
        except Exception:
            pass


async def _wait_for_addresses(page: Page, timeout_ms: int = 60000) -> bool:
    import re, time as _t
    addr_pattern = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
    end = _t.time() + (timeout_ms / 1000)
    while _t.time() < end:
        try:
            await _try_dismiss_consent(page)
            html = await page.content()
            if addr_pattern.search(html):
                return True
            try:
                txt = await page.evaluate("document.body?.innerText || ''")
                if addr_pattern.search(txt):
                    return True
            except Exception:
                pass
        except Exception:
            pass
        await page.wait_for_timeout(500)
    return False


class PlaywrightBrowserMissingError(RuntimeError):
    pass


class PlaywrightBlockedError(RuntimeError):
    pass


def _is_retryable(e: Exception) -> bool:
    # Don't retry when Playwright browsers are not installed
    msg = str(e)
    if "Executable doesn't exist" in msg and "playwright install" in msg:
        return False
    # Don't retry on selector syntax errors
    if "Unexpected token" in msg and "selector" in msg:
        return False
    # Don't retry on Cloudflare/blocking errors
    if isinstance(e, PlaywrightBlockedError):
        return False
    return True


async def _apply_stealth(page: Page):
    # No-op: we now inject at the context level to avoid duplicate redefinitions
    return

async def _apply_context_stealth_headers(page: Page):
    # Align headers minimally and inject stealth at the context level
    try:
        ctx = page.context
        # Keep headers minimal to avoid triggering CORS preflights
        await ctx.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
        })
        # Inject init script once, with guards to avoid redefine errors
        await ctx.add_init_script(
            """
            try {
                const desc = Object.getOwnPropertyDescriptor(navigator, 'webdriver');
                if (!desc || desc.configurable) {
                    Object.defineProperty(navigator, 'webdriver', { configurable: true, get: () => undefined });
                }
            } catch (e) {}
            try { Object.defineProperty(navigator, 'languages', { configurable: true, get: () => ['en-US', 'en'] }); } catch (e) {}
            try { Object.defineProperty(navigator, 'plugins', { configurable: true, get: () => [1,2,3] }); } catch (e) {}
            try { window.chrome = window.chrome || { runtime: {} }; } catch (e) {}
            try { Object.defineProperty(navigator, 'platform', { configurable: true, get: () => 'Win32' }); } catch (e) {}
            try { Object.defineProperty(navigator, 'deviceMemory', { configurable: true, get: () => 8 }); } catch (e) {}
            try { Object.defineProperty(navigator, 'hardwareConcurrency', { configurable: true, get: () => 8 }); } catch (e) {}
            try {
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter){
                    if (parameter === 37445) return 'Intel Inc.'; // UNMASKED_VENDOR_WEBGL
                    if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
                    return getParameter.apply(this, [parameter]);
                };
            } catch (e) {}
            try {
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : originalQuery(parameters)
                );
            } catch (e) {}
            """
        )
    except Exception:
        pass


def _parse_proxy(proxy: str) -> dict:
    """Parse a proxy URL into Playwright proxy options."""
    scheme, rest = (proxy.split("://", 1) + [""])[:2]
    proxy_opts = {"server": proxy}
    if "@" in rest:
        creds, _host = rest.split("@", 1)
        if ":" in creds:
            username, password = creds.split(":", 1)
            proxy_opts.update({"username": username, "password": password})
    return proxy_opts


def _random_user_agent() -> str:
    # Modern Chrome UA, randomize Windows version and Chrome build
    win_ver = random.choice(["10.0; Win64; x64", "11.0; Win64; x64"])
    chrome_major = random.choice([126, 127, 128])
    build_minor = random.randint(0, 9)
    build_patch = random.randint(10, 99)
    return (
        f"Mozilla/5.0 (Windows NT {win_ver}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_major}.0.{build_minor}{build_patch}.100 Safari/537.36"
    )


def _ua_hints(ua: str) -> dict:
    """Generate reasonable Sec-CH-UA headers from a Chrome UA string."""
    import re
    m = re.search(r"Chrome/(\d+)", ua)
    major = m.group(1) if m else "128"
    # Avoid exact brand set to reduce brittleness
    sec_ch_ua = f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not.A/Brand";v="99"'
    return {
        "Sec-CH-UA": sec_ch_ua,
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": "Windows",
    }


@retry(stop=stop_after_attempt(2), wait=wait_fixed(1), retry=retry_if_exception(lambda e: _is_retryable(e)))
async def scrape_gmgn(
    url: str = GMGN_URL,
    expected_count: int = 100,
    headless: bool = False,
    browser_channel: str = "chrome",
    chrome_profile_path: Optional[str] = None,
    proxy: Optional[str] = None,
    cdp_url: Optional[str] = None,
) -> List[str]:
    # Session storage file for non-persistent contexts
    sessions_dir = Path.cwd() / ".sessions"
    try:
        sessions_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    storage_state_file = sessions_dir / "gmgn_ai_pw_storage.json"
    async with async_playwright() as pw:
        browser = None
        context = None
        try:
            # Option 0: Attach to an existing Chrome via CDP if provided (e.g., ws:// or http://localhost:9222)
            if cdp_url:
                try:
                    browser = await pw.chromium.connect_over_cdp(cdp_url)
                    # New regular context; load storage state if we have one
                    storage = str(storage_state_file) if storage_state_file.exists() else None
                    context = await browser.new_context(storage_state=storage)
                except Exception as e:
                    logging.warning("CDP attach failed (%s), falling back to launch.", e)
            # Try a persistent context if a Chrome profile path is provided
            if not context and chrome_profile_path:
                try:
                    p = Path(chrome_profile_path)
                    if p.exists():
                        if p.name.lower().startswith("profile") or p.name == "Default":
                            user_data_dir = p.parent
                            profile_arg = f"--profile-directory={p.name}"
                        else:
                            # Assume this is the User Data root; let Chrome pick Default
                            user_data_dir = p
                            profile_arg = None

                        logging.info(
                            "Launching persistent Chrome with user_data_dir=%s profile_arg=%s",
                            user_data_dir,
                            profile_arg,
                        )
                        extra_args = []
                        if profile_arg:
                            extra_args.append(profile_arg)
                        if headless and browser_channel == "chrome":
                            extra_args.append("--headless=new")
                        launch_kwargs = dict(
                            user_data_dir=str(user_data_dir),
                            headless=headless,
                            channel=browser_channel,
                        )
                        if extra_args:
                            launch_kwargs["args"] = extra_args
                        # Drop automation-identifying default flags when possible
                        launch_kwargs["ignore_default_args"] = [
                            "--enable-automation",
                            "--disable-extensions",
                            "--no-first-run",
                            "--no-default-browser-check",
                            "--password-store=basic",
                            "--use-mock-keychain",
                            "--disable-component-update",
                        ]
                        if proxy:
                            launch_kwargs["proxy"] = _parse_proxy(proxy)
                        context = await pw.chromium.launch_persistent_context(**launch_kwargs)
                except Exception as e:
                    logging.warning("Persistent profile launch failed, falling back to regular context: %s", e)

            # If no persistent context, launch a regular browser context
            if not context:
                try:
                    launch_args = {"headless": headless, "channel": browser_channel}
                    if headless and browser_channel == "chrome":
                        launch_args["args"] = ["--headless=new"]
                    # Add common flags to reduce automation signals
                    extra_flags = [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ]
                    if "args" in launch_args:
                        launch_args["args"].extend(extra_flags)
                    else:
                        launch_args["args"] = extra_flags
                    # Drop automation-identifying default flags when possible
                    launch_args["ignore_default_args"] = [
                        "--enable-automation",
                        "--disable-extensions",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--password-store=basic",
                        "--use-mock-keychain",
                        "--disable-component-update",
                    ]
                    if proxy:
                        launch_args["proxy"] = _parse_proxy(proxy)
                    browser = await pw.chromium.launch(**launch_args)
                except Exception:
                    # Fallback to bundled Chromium without channel
                    fallback_args = {"headless": headless}
                    if headless:
                        fallback_args["args"] = ["--headless=new"]
                    # Same extra flags
                    fallback_args.setdefault("args", []).extend([
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ])
                    if proxy:
                        fallback_args["proxy"] = _parse_proxy(proxy)
                    browser = await pw.chromium.launch(**fallback_args)

                storage = str(storage_state_file) if storage_state_file.exists() else None
                context = await browser.new_context(
                    permissions=["clipboard-read", "clipboard-write"],
                    user_agent=_random_user_agent(),
                    bypass_csp=True,
                    viewport={
                        "width": random.choice([1366, 1440, 1536, 1920]),
                        "height": random.choice([768, 900, 1080]),
                    },
                    storage_state=storage,
                )

            page = await context.new_page()
            await _apply_context_stealth_headers(page)
            # Add realistic client hints based on the UA of this context
            try:
                ua = await page.evaluate("navigator.userAgent")
            except Exception:
                ua = None
            if ua:
                try:
                    await context.set_extra_http_headers({**_ua_hints(ua)})
                except Exception:
                    pass

            # Warm-up: visit site root first to set cookies and initial signals
            try:
                await page.goto("https://gmgn.ai/", wait_until="domcontentloaded")
                await page.wait_for_timeout(500)
                # Try to accept cookie banners early
                for selector in [
                    "button:has-text('Accept')",
                    "button:has-text('Agree')",
                    "text=Accept All",
                ]:
                    try:
                        loc = page.locator(selector)
                        if await loc.count() > 0:
                            await loc.first.click(timeout=1500)
                    except Exception:
                        pass
                # Small human-like scrolls on home
                for _ in range(2):
                    await page.mouse.wheel(0, random.randint(200, 600))
                    await asyncio.sleep(random.uniform(0.15, 0.35))
                home_html = await page.content()
                if (
                    "Cloudflare Ray ID" in home_html
                    or "cf-chl-bypass" in home_html
                    or "Sorry, you have been blocked" in home_html
                    or "Access denied" in home_html
                    or "captcha" in home_html.lower()
                ):
                    raise PlaywrightBlockedError("Blocked on homepage. IP/proxy likely flagged.")
            except Exception:
                # Ignore warm-up failures and proceed to target
                pass

            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            # Small human-like scrolls
            for _ in range(3):
                await page.mouse.wheel(0, random.randint(200, 600))
                await asyncio.sleep(random.uniform(0.15, 0.35))

            # Ensure addresses are present before extracting
            try:
                await _wait_for_addresses(page, timeout_ms=60000)
            except Exception:
                pass

            # Detect Cloudflare/block pages and abort early
            html = await page.content()
            if (
                "Cloudflare Ray ID" in html
                or "cf-chl-bypass" in html
                or "Sorry, you have been blocked" in html
                or "Access denied" in html
                or "captcha" in html.lower()
            ):
                raise PlaywrightBlockedError(
                    "Blocked by site protection (Cloudflare). Stealth is enabled using Chrome. Try again, or toggle headless off and retry."
                )

            # Sometimes site shows cookie/banner; try dismiss
            for selector in [
                "button:has-text('Accept')",
                "button:has-text('Agree')",
                "text=Accept All",
            ]:
                try:
                    loc = page.locator(selector)
                    if await loc.count() > 0:
                        await loc.first.click(timeout=2000)
                except Exception:
                    pass

            addrs = await _collect_addresses_by_copy(page, expected_count=expected_count)

            # Deduplicate while preserving order
            seen = set()
            ordered = []
            for a in addrs:
                if a not in seen:
                    seen.add(a)
                    ordered.append(a)
            return ordered

        except Exception as e:
            text = str(e)
            if "Executable doesn't exist" in text and "playwright install" in text:
                raise PlaywrightBrowserMissingError(
                    "Playwright browsers are not installed. Open PowerShell and run: python -m playwright install"
                )
            raise
        finally:
            try:
                # Save storage state for future runs (only when we created a context)
                try:
                    if context:
                        context_state_path = str(storage_state_file)
                        await context.storage_state(path=context_state_path)
                except Exception:
                    pass
                if context:
                    await context.close()
            finally:
                # Do not close an external CDP-attached browser
                if browser and not cdp_url:
                    await browser.close()


def save_addresses_to_csv(addresses: List[str], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["address"])  # header
        for a in addresses:
            writer.writerow([a])
    return out_path


def scrape_gmgn_sync(
    url: str = GMGN_URL,
    expected_count: int = 100,
    headless: bool = False,
    browser_channel: str = "chrome",
    chrome_profile_path: Optional[str] = None,
    proxy: Optional[str] = None,
    cdp_url: Optional[str] = None,
) -> List[str]:
    return asyncio.run(
        scrape_gmgn(
            url=url,
            expected_count=expected_count,
            headless=headless,
            browser_channel=browser_channel,
            chrome_profile_path=chrome_profile_path,
            proxy=proxy,
            cdp_url=cdp_url,
        )
    )

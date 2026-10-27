#!/usr/bin/env python3
"""Fetch pages through CloakBrowser for generate-instances-json.sh.

Prints "ready" once the browser runs, then reads one URL per line on stdin.
For each it writes the body to a temporary file and prints
"FILE CODE TLS REDIRECT": the HTTP status (000 without a response), 1 if the
server accepted the connection (0 if not) and the final URL if the page ended
up on another host.
"""

import asyncio
import sys
import tempfile
from urllib.parse import urlsplit

from cloakbrowser import launch_async

# Seconds a bot check gets to let the browser through.
WAIT = 15

# Navigation errors that mean nothing accepted the connection. goto waits only
# for the response to start, so its timeout means there was none.
UNREACHABLE = (
    "Timeout",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_NAME_RESOLUTION_FAILED",
    "ERR_ADDRESS_UNREACHABLE",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_TIMED_OUT",
    "ERR_CERT_",
    "ERR_SSL_",
)


def from_redlib(body):
    return '"crate_version"' in body or 'href="/style.css' in body


async def fetch(context, url):
    page = await context.new_page()
    last = None

    def on_response(response):
        nonlocal last
        if response.request.is_navigation_request() and response.frame == page.main_frame:
            last = response

    page.on("response", on_response)
    body = ""
    try:
        await page.goto(url, timeout=20000, wait_until="commit")
    except Exception as e:
        await page.close()
        if last:
            return "", f"{last.status:03}", 1, ""
        return "", "000", 0 if any(x in str(e) for x in UNREACHABLE) else 1, ""

    for _ in range(WAIT):
        code = last.status if last else 0
        try:
            if "json" in (last.headers.get("content-type", "") if last else ""):
                body = await page.inner_text("body")
            else:
                body = await page.content()
        except Exception:
            body = ""
        if from_redlib(body) or code >= 500 or (code >= 400 and code not in (401, 403, 429)):
            break
        await page.wait_for_timeout(1000)

    final = page.url
    await page.close()
    redirect = final if urlsplit(final).hostname != urlsplit(url).hostname else ""
    return body, f"{last.status if last else 0:03}", 1, redirect


async def main():
    browser = await launch_async(headless=True, humanize=True)
    context = await browser.new_context()
    print("ready", flush=True)

    loop = asyncio.get_running_loop()
    while url := (await loop.run_in_executor(None, sys.stdin.readline)).strip():
        body, code, tls, redirect = await fetch(context, url)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".body") as f:
            f.write(body)
        print(f.name, code, tls, redirect, flush=True)

    await browser.close()


asyncio.run(main())

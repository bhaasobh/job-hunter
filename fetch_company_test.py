"""Standalone dry-run fetch tester for a single company endpoint."""

import asyncio
import json
from pprint import pprint

import httpx


TEST_SOURCE = {
    "company": "samsung",
    "method": "POST",
    "url": "https://sec.wd3.myworkdayjobs.com/wday/cxs/sec/Samsung_Careers/jobs",
    "payload": {
        "limit": 20,
        "offset": 0,
        "searchText": "",
    },
    "headers": {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    },
}


async def fetch_company_test(client: httpx.AsyncClient, source: dict):
    """Fetch one company endpoint and print the raw response."""
    company = source["company"]
    method = str(source.get("method", "GET")).upper()
    url = source["url"]
    payload = source.get("payload")
    headers = source.get("headers") or {}

    print(f"Fetching jobs for {company}...")
    print(f"Method: {method}")
    print(f"URL: {url}")
    if payload:
        print("Payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=True))

    if method == "POST":
        response = await client.post(url, json=payload, headers=headers, timeout=30)
    else:
        response = await client.get(url, params=payload, headers=headers, timeout=30)

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        data = response.text

    print(f"\nStatus: {response.status_code}")
    print("Response preview:")
    if isinstance(data, (dict, list)):
        pprint(data)
    else:
        print(data[:5000])

    return data


async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        await fetch_company_test(client, TEST_SOURCE)


if __name__ == "__main__":
    asyncio.run(main())


import asyncio
import httpx
import json
import pytest

@pytest.mark.integration
@pytest.mark.anyio
async def test_cisco_api():
    url = "https://careers.cisco.com/widgets"
    payload = {
        "sortBy": "",
        "subsearch": "",
        "from": 0,
        "jobs": True,
        "counts": True,
        "all_fields": ["category", "raasJobRequisitionType", "country", "state", "city", "type", "RemoteType"],
        "pageName": "search-results",
        "size": 10,
        "clearAll": False,
        "jdsource": "facets",
        "isSliderEnable": False,
        "pageId": "page4",
        "siteType": "external",
        "keywords": "",
        "global": True,
        "selected_fields": {"country": ["Israel"]},
        "lang": "en_global",
        "deviceType": "desktop",
        "country": "global",
        "refNum": "CISCISGLOBAL",
        "ddoKey": "refineSearch"
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Try without CSRF first
        response = await client.post(url, json=payload, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            jobs = data.get("refineSearch", {}).get("data", {}).get("jobs", [])
            print(f"Found {len(jobs)} jobs")
            if jobs:
                print(f"Example job: {jobs[0].get('title')} - {jobs[0].get('applyUrl')}")
        else:
            print(response.text[:500])

if __name__ == "__main__":
    asyncio.run(test_cisco_api())

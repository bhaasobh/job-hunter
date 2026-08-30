
import asyncio
import httpx
import pytest

@pytest.mark.integration
@pytest.mark.anyio
async def test_cisco_workday():
    url = "https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs"
    payload = {
        "appliedFacets": {
            "Location_Country": ["084562884af243748dad7c84c304d89a"] # Typical Israel ID, let's check
        },
        "limit": 20,
        "offset": 0,
        "searchText": ""
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            postings = data.get('jobPostings', [])
            print(f"Found {len(postings)} jobs")
            if postings:
                print(f"First job: {postings[0].get('title')}")
                print(f"Path: {postings[0].get('externalPath')}")
        else:
            print(response.text[:500])

if __name__ == "__main__":
    asyncio.run(test_cisco_workday())

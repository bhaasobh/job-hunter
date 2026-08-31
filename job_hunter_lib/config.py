"""Shared configuration for the job hunter."""

from pathlib import Path
import os

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CV_FILE_PATH = os.getenv("CV_FILE_PATH", "cv.txt")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.8:latest")
OLLAMA_TIMEOUT_SECONDS = max(30, int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600")))
SCHEDULE_INTERVAL_HOURS = max(1, int(os.getenv("SCHEDULE_INTERVAL_HOURS", "4")))
SCHEDULE_MIN_AI_SCORE = max(0, min(100, int(os.getenv("SCHEDULE_MIN_AI_SCORE", "75"))))
SCHEDULE_MAX_TELEGRAM_JOBS = max(1, int(os.getenv("SCHEDULE_MAX_TELEGRAM_JOBS", "10")))
SCHEDULE_BOOTSTRAP_SILENT = os.getenv("SCHEDULE_BOOTSTRAP_SILENT", "true").lower() in {"1", "true", "yes"}
TELEGRAM_CV_MODE = os.getenv("TELEGRAM_CV_MODE", "latest")
TELEGRAM_CV_MIN_LENGTH = int(os.getenv("TELEGRAM_CV_MIN_LENGTH", "200"))
CV_STORAGE_DIR = Path(os.getenv("CV_STORAGE_DIR", "cvs"))
MONGO_URI = os.getenv("MONGO_URI", "").strip()

GREENHOUSE_BOARDS = [
    "asteralabs",
    "saltsecurity",
    "oasissecurity",
    "similarweb",
    "gongio",
    "bringg",
    "transmitsecurity",
    "databricks",
    "armissecurity",
    "appsflyer",
    "riskified",
    "via",
    "melio",
    "forter",
    "orcasecurity",
    "torq",
    "fireblocks",
    "taboola",
    "yotpo",
    "payoneer",
    "honeybook",
    "jfrog",
    "apiiro",
    "cymulate",
    "lightricks",
    "sisense",
    "axonius",
    "pagayais",
    "guidde",
    "tenableinc",
    "descope",
    "wizinc",
    "catonetworks",
    "cybereason",
    "connecteam",
]
GREENHOUSE_COMPANY_ALIASES = {
    "wizinc": "wiz",
    "gongio": "gong",
    "asteralabs": "astera_labs",
    "saltsecurity": "salt_security",
    "oasissecurity": "oasis_security",
    "transmitsecurity": "transmit_security",
}




# Workday does not expose a global public index, so these must be concrete public
# job collection endpoints for specific employers, for example:
# https://company.wdX.myworkdayjobs.com/wday/cxs/company/site/jobs

qualcomm_source = {
    "company": "qualcomm",
    "base_url": "https://careers.qualcomm.com/api/pcsx/search?domain=qualcomm.com&query=&location=israel&start=0&sort_by=timestamp"
    }
nvidia_source = {
    "company": "nvidia",
    "base_url": "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
}
ELBIT_SOURCE = {
    "company": "elbit_systems",
    "url": "https://elbitsystemscareer.com/cron/jobs.json",
    "careers_url": "https://elbitsystemscareer.com/jobs/",
    "job_url": "https://elbitsystemscareer.com/job/",
}
ISCAR_SOURCE = {
    "company": "iscar",
    "url": "https://www.iscar.com/marcom/iscar-career-job-list/",
    "text_proxy": "https://r.jina.ai/http://www.iscar.com/marcom/iscar-career-job-list/",
    "max_pages": 20,
}
BANK_SOURCES = [
    {
        "company": "bank_leumi",
        "url": "https://www.leumi.co.il/leumi_main/searchjobs",
        "kind": "leumi",
    },
    {
        "company": "mizrahi_tefahot",
        "url": "https://www.mizrahi-tefahot.co.il/about-mizrahi-tefahot-he/career/open-jobs/",
        "kind": "mizrahi",
    },
]
GOVERNMENT_JOBS_SOURCE = {
    "company": "israel_civil_service",
    "url": "https://www.gov.il/he/collectors/publications/?officeId=bfe22d82-2309-43ff-94d7-1eeb873ab368",
    "search_url": "https://www.bing.com/search",
}
BIG_TECH_SOURCES = [
    {"company": "amazon", "kind": "amazon", "url": "https://www.amazon.jobs/en/search.json"},
    {"company": "apple", "kind": "apple", "url": "https://jobs.apple.com/en-il/search?location=israel-ISR"},
    {"company": "google", "kind": "google", "url": "https://www.google.com/about/careers/applications/jobs/results/?location=Israel"},
    {"company": "microsoft", "kind": "microsoft", "url": "https://careers.microsoft.com/v2/global/en/locations/israel.html"},
]
WORKDAY_SOURCES = [
    {
        "company": "microchip_technology",
        "base_url": "https://wd5.myworkdaysite.com/wday/cxs/microchiphr/External/jobs",
        "payload": {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Israel"},
    },
    {
        "company": "marvell",
        "base_url": "https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers/jobs",
        "payload": {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Israel"},
    },
    {
        "company": "applied_materials",
        "base_url": "https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs",
        "payload": {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Israel"},
    },
    {
        "company": "kla",
        "base_url": "https://kla.wd1.myworkdayjobs.com/wday/cxs/kla/Search/jobs",
        "payload": {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Israel"},
    },
    {
        "company": "cadence",
        "base_url": "https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/External_Careers/jobs",
        "payload": {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Israel"},
    },
    {
        "company": "intel",
        "base_url": "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs",
        "payload": {
            "appliedFacets": {
                "locations": [
                    "1e4a4eb3adf101cb242c9e74bf8189cd",
                    "1e4a4eb3adf101aaeda8a474bf818ecd",
                    "1e4a4eb3adf101f41cd29774bf8184cd",
                    "1e4a4eb3adf1013563ba9174bf817fcd",
                ]
            },
            "limit": 20,
            "offset": 0,
            "searchText": "",
        },
    },
    {
        "company": "dell",
        "base_url": "https://dell.wd1.myworkdayjobs.com/wday/cxs/dell/External/jobs",
        "payload": {
            
            "appliedFacets": {
                "Location_Country": [
                "084562884af243748dad7c84c304d89a"
                ]
  }

        }
            
    },
    {
        "company": "hpe",
        "base_url": "https://hpe.wd5.myworkdayjobs.com/wday/cxs/hpe/Jobsathpe/jobs",
        "payload": {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": "Israel",
        },
    },
    {
        "company": "paloalto",
        "base_url": "https://paloaltonetworks.wd5.myworkdayjobs.com/wday/cxs/paloaltonetworks/panwexternalcareers/jobs",
        "payload": {
            "appliedFacets": {
                "locations": [
                    "462d9b819ff31060221ce2cad22df7c3",
                    "e62cc4173be310016a98d270a39f0000"
                ]
            },
            "limit": 20,
            "offset": 0,
            "searchText": "",
        },
    },
    {
        "company": "cisco",
        "base_url": "https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs",
        "payload": {
            "appliedFacets": {
                "locations": [
                    "3419053a4e7d1001f4eede2208d40000",
                    "3419053a4e7d1001f4ec9c9face40000"
                ]
            },
            "limit": 20,
            "offset": 0,
            "searchText": "",
        },
    },
    {
        "company": "genpact",
        "base_url": "https://genpact.wd108.myworkdayjobs.com/wday/cxs/genpact/External_Careers/jobs",
        "payload": {
            "appliedFacets": {
                "locations": [
                    "faddece16d451000bf36350197990000",
                ]
            },
            "limit": 20,
            "offset": 0,
            "searchText": "",
        },
    }
]

CAREER_PAGE_SOURCES = [
    {
        "company": "tesnet",
        "url": "https://tesnet-group.com/job/",
        "kind": "tesnet",
        "assume_israel": True,
    },
    {
        "company": "sqlink",
        "url": "https://www.sqlink.com/career/",
        "kind": "sqlink",
        "assume_israel": True,
    },
    {
        "company": "zota",
        "url": "https://careers.zota.com/",
        "api_url": "https://careers.zota.com/api/offers/",
        "kind": "recruitee",
    },
    {
        "company": "gav_systems",
        "url": "https://gav.co.il/jobs/",
        "api_url": "https://gav.co.il/wp-json/wp/v2/jobs",
        "kind": "gav_wp",
        "assume_israel": True,
    },
    {
        "company": "teradyne",
        "url": "https://jobs.teradyne.com/search/",
        "kind": "successfactors",
        "search_params": {"q": "", "locationsearch": "Israel"},
    },
    {"company": "coralogix", "url": "https://coralogix.com/careers/", "path_markers": ["/careers/co/"]},
    {"company": "snyk", "url": "https://snyk.io/careers/all-jobs/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "hailo", "url": "https://hailo.ai/company-overview/careers/", "path_markers": ["/careers/hailo-has-amazing-openings/"], "assume_israel": True},
    {"company": "innoviz_technologies", "url": "https://innoviz.tech/careers", "path_markers": ["/career/", "/careers/", "/job/"], "assume_israel": True},
    {"company": "ramon_space", "url": "https://ramon.space/careers/", "path_markers": ["/career/"], "assume_israel": True},
    {"company": "twine_security", "url": "https://www.twinesecurity.com/careers", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "astrix_security", "url": "https://astrix.security/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "walkme", "url": "https://www.walkme.com/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "playtika", "url": "https://www.playtika.com/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "ray_security", "url": "https://www.ray.security/careers", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "entro_security", "url": "https://entro.security/careers", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "redis", "url": "https://redis.io/company/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "outbrain", "url": "https://www.teads.com/teads-careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "singular", "url": "https://www.singular.net/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "tipalti", "url": "https://tipalti.com/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "rapyd", "url": "https://www.rapyd.net/company/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "hibob", "url": "https://www.hibob.com/careers/", "path_markers": ["/jobs/"]},
    {"company": "papaya_global", "url": "https://www.papayaglobal.com/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "guesty", "url": "https://www.guesty.com/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "lemonade", "url": "https://www.lemonade.com/careers", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "wing_security", "url": "https://withwings.ai/", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "cynet", "url": "https://www.cynet.com/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "ox_security", "url": "https://www.ox.security/careers", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "realsense", "url": "https://www.realsenseai.com/about/", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "vayyar", "url": "https://apply.workable.com/vayyar/", "path_markers": ["/vayyar/j/"], "assume_israel": True},
    {"company": "storedot", "url": "https://www.store-dot.com/careers", "path_markers": ["/job/", "/jobs/", "/careers/"], "assume_israel": True},
    {"company": "autotalks", "url": "https://auto-talks.com/careers2/", "path_markers": ["/career/", "/careers/"], "assume_israel": True},
    {
        "company": "strauss_group",
        "url": "https://www.strauss-group.co.il/career/jobs/",
        "kind": "strauss",
        "assume_israel": True,
    },
    {
        "company": "proceed",
        "url": "https://proceed.co.il/career",
        "api_url": "https://services.adamtotal.co.il/api/Career/GetOrdersDetails?api_key=123456_%401Mda",
        "api_token": "7BC99795-A673-44C7-B2F9-7036F84A844F",
        "kind": "proceed",
        "assume_israel": True,
    },
    {
        "company": "ness_technologies",
        "url": "https://www.ness-tech.co.il/careers/recruit",
        "api_url": "https://www.ness-tech.co.il/careers/api/Careers/GetOrderDetailsList",
        "kind": "ness",
        "assume_israel": True,
    },
    {
        "company": "qualitest",
        "url": "https://careers.quality-ai.com/search/",
        "kind": "qualitest",
        "assume_israel": True,
    },
    {
        "company": "philips",
        "url": "https://www.careers.philips.com/il/en/search-results",
        "kind": "philips",
        "assume_israel": True,
    },
    {
        "company": "siemens",
        "url": "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/",
        "kind": "siemens",
        "assume_israel": True,
    },
    {"company": "mobileye", "url": "https://careers.mobileye.com/jobs", "path_markers": ["/jobs/"], "assume_israel": True},
    {
        "company": "tower_semiconductor",
        "url": "https://careers.towersemi.com/our-loactions/israel/",
        "proxy_url": "https://r.jina.ai/https://careers.towersemi.com/our-loactions/israel/",
        "path_markers": ["/job-description"],
        "assume_israel": True,
    },
    {"company": "solaredge", "url": "https://corporate.solaredge.com/en/careers/open-positions", "path_markers": ["/job/", "/position/"]},
    {"company": "synopsys", "url": "https://careers.synopsys.com/", "path_markers": ["/job/", "/jobs/"]},
    {"company": "nova", "url": "https://nova.co.il/location_filter/israel/", "proxy_url": "https://r.jina.ai/http://nova.co.il/location_filter/israel/", "path_markers": ["/position/", "/careers/"], "assume_israel": True},
    {"company": "camtek", "url": "https://www.camtek.com/careers/", "path_markers": ["/careers/open-positions/"], "assume_israel": True},
    {
        "company": "fivesgroup",
        "url": "https://jobs.fivesgroup.com/en/search",
        "offer_url": "https://jobs.fivesgroup.com/en/offer/",
        "sitemap_url": "https://jobs.fivesgroup.com/sitemap.xml",
        "kind": "fivesgroup",
        "assume_israel": True,
    },
    {"company": "valens_semiconductor", "url": "https://www.valens.com/positions/", "proxy_url": "https://r.jina.ai/http://www.valens.com/positions/", "path_markers": ["/position/"], "assume_israel": True},
    {"company": "proteantecs", "url": "https://www.proteantecs.com/careers", "path_markers": ["/careerinfo", "/job/", "/jobs/", "/position/"], "assume_israel": True},
    {"company": "ceva", "url": "https://www.ceva-ip.com/career/", "path_markers": ["/job/", "/jobs/", "/position/", "/career/"], "assume_israel": True},
    {"company": "check_point", "url": "https://careers.checkpoint.com/index.php?a=search&fa%5B%5D=country_ss%3AIsrael&module=cpcareers&q=&sort=", "proxy_url": "https://r.jina.ai/http://careers.checkpoint.com/index.php?a=search%26fa%5B%5D=country_ss%3AIsrael%26module=cpcareers%26q=%26sort=", "path_markers": ["/job/", "/jobs/", "/index.php"], "assume_israel": True},
    {"company": "sentinelone", "url": "https://www.sentinelone.com/jobs/", "path_markers": ["/jobs/"]},
    {"company": "aqua_security", "url": "https://www.aquasec.com/about-us/careers/", "proxy_url": "https://r.jina.ai/http://www.aquasec.com/about-us/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "imperva", "url": "https://www.imperva.com/company/careers/", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "cye", "url": "https://jobs.lever.co/CYE", "path_markers": ["/cye/"]},
    {"company": "pentera", "url": "https://www.comeet.com/jobs/pentera/C5.00D", "path_markers": ["/jobs/pentera/"]},
    {"company": "xm_cyber", "url": "https://xmcyber.com/job-listing/", "path_markers": ["/job-listing/"]},
    {"company": "silverfort", "url": "https://www.silverfort.com/careers/", "path_markers": ["/job/", "/jobs/", "/position/", "/careers/"]},
    {"company": "akamai_guardicore", "url": "https://www.akamai.com/careers", "proxy_url": "https://r.jina.ai/http://www.akamai.com/careers", "path_markers": ["/job/", "/jobs/", "/careers/"]},
    {"company": "radware", "url": "https://www.radware.com/careers/", "path_markers": ["/job/", "/jobs/", "/career/"]},
    {"company": "radiflow", "url": "https://www.radiflow.com/careers/", "proxy_url": "https://r.jina.ai/http://www.radiflow.com/careers/", "path_markers": ["/job/", "/jobs/", "/position/", "/career/"]},
]

SKILL_KEYWORDS = [
    "python",
    "c",
    "c++",
    "c#",
    "java",
    "sql",
    "assembly",
    "linux",
    "windows",
    "aws",
    "docker",
    "rest api",
    "automation",
    "validation",
    "debug",
    "embedded",
    "pcie",
    "usb",
    "cpu",
    "gpu",
    "cybersecurity",
    "cloud",
    "algorithms",
    "network",
]
COMEET_SOURCES = [
    {"company": "dream", "uid": "99.002", "token": "99242FE9921CB6042FE396C42FE132442FE", "assume_israel": True},
    {"company": "cyera", "uid": "17.008", "token": "7182A90154871823783FD838C031A802378"},
    {"company": "guardio", "uid": "57.000", "token": "7502BE015F0249041D01D40EA03A801D40EA0"},
    {"company": "grip_security", "uid": "A8.001", "token": "8A133C63C672B253C673C67019E311424DA9"},
    {"company": "hunters", "uid": "67.007", "token": "7672C6A163533D11D9C429F33D10250333D1"},
    {"company": "reco", "uid": "3A.00D", "token": "A3D47AB28F405C2505C2551E8333151E8"},
    {"company": "mitiga", "uid": "26.00B", "token": "62B250262B012811ED718AC128112813158"},
    {"company": "minimus", "uid": "19.00B", "token": "91B36A251F31B5148D81B513FBD51F301B51"},
    {"company": "sygnia", "uid": "78.00A", "token": "87A32DC3B5687A196E2A6210F43B5610F43B56"},
    {"company": "arbe_robotics", "uid": "C6.001", "token": "6C12886D821B0414432886144328862F472F47"},
    {"company": "trieye", "uid": "A6.00E", "token": "6AE2814D5CD5C1AB8140A35706AE2EC22814"},
    {
        "company": "fiverr",
        "uid": "60.002",
        "token": "62188018812631018862C4188"
    },
    {
        "company": "monday",
        "uid": "41.00B",
        "token": "14B52C52C67790D3E1296BA37C20"
    },
    {
        "company": "samsung",
        "uid": "D4.005",
        "token": "4D518291CFE13540135413544D518291CFE"
    },
    {
        "company": "abra_strategy",
        "uid": "12.003",
        "token": "21384C109806394262131098213426"
    },
    {
        "company": "abra_rnd",
        "uid": "15.007",
        "token": "517197323A1A2E1973A2E145CA2E0A2E"
    },
    {
        "company": "majestic_labs",
        "uid": "AA.004",
        "token": "AA44A7C35345FC44A7C5FC4055205FC42A90"
    },
    {
        "company": "biocatch",
        "uid": "03.00E",
        "token": "30EF4630E92A1562156292A92A61C92A"
    },
    {
        "company": "ceragon",
        "uid": "D3.003",
        "token": "3D3131FF4C01AC57A61AC51E98131FF4C"
    },
    {
        "company": "voyantis",
        "uid": "86.00B",
        "token": "68B2742D1600D16020B71A2C2742"
    },
    {
        "company": "weski",
        "uid": "F8.00C",
        "token": "8FC35E847E03EE423F011F811F801AF435E8",
        "assume_israel": True,
    },
    {
        "company": "qedma",
        "uid": "7A.006",
        "token": "A76493A344E14EC029D853B01F621F62A76"
    },
    {
        "company": "vega",
        "uid": "C9.009",
        "token": "9C9447F139227241392272430ED30ED04E48"
    },
    {
        "company": "g2_risk_solutions",
        "uid": "C9.003",
        "token": "9C3445513861D491D49445557DB30CF44551D49"
    },
]

SMARTRECRUITERS_SOURCES = [
    {
        "company": "cyberark",
        "url": "https://api.smartrecruiters.com/v1/companies/Cyberark1/postings"
    },
    {
        "company": "western_digital",
        "url": "https://api.smartrecruiters.com/v1/companies/WesternDigital/postings",
    }
]

ASHBY_SOURCES = [
    {"company": "tavily", "board": "tavily"},
    {"company": "harmony", "board": "harmony"},
    {"company": "irregular", "board": "Irregular"},
    {"company": "nexxen", "board": "nexxen"},
]

SUPPORTED_COMPANIES = sorted(set(
    [GREENHOUSE_COMPANY_ALIASES.get(board, board) for board in GREENHOUSE_BOARDS]
    + [qualcomm_source["company"], nvidia_source["company"], ELBIT_SOURCE["company"], ISCAR_SOURCE["company"]]
    + [source["company"] for source in BANK_SOURCES]
    + [GOVERNMENT_JOBS_SOURCE["company"]]
    + [source["company"] for source in BIG_TECH_SOURCES]
    + [source["company"] for source in WORKDAY_SOURCES]
    + [source["company"] for source in SMARTRECRUITERS_SOURCES]
    + [source["company"] for source in COMEET_SOURCES]
    + [source["company"] for source in ASHBY_SOURCES]
    + [source["company"] for source in CAREER_PAGE_SOURCES]
))

ISRAEL_LOCATION_KEYWORDS = [
    "israel",
    "tel aviv",
    "haifa",
    "jerusalem",
    "herzliya",
    "petah tikva",
    "ra'anana",
    "raanana",
    "netanya",
    "rishon lezion",
    "beer sheva",
    "bnei brak",
    "shefaram",
    "binyamina",
    "caesarea",
    "yokneam",
    "migdal haemek",
    "rehovot",
    "hod hasharon",
]
JUNIOR_KEYWORDS = [
    "junior",
    "student",
    "graduate",
    "entry level",
    "new grad",
]

import os
import re
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# ---------------- CONFIG ----------------

CHROME_PROFILE_PATH = r"CHROME_PROFILE"
PROFILE_NAME = "NUMBER_AT_THE_END_OF_CHROME_PROFILE"
JOB_URL = "https://www.linkedin.com/hiring/applicants/?rating=HIRER_SHORTLISTED&jobId=JOB_ID"
DOWNLOAD_FOLDER = r"PATH_TO_TARGET_DOWNLOAD_FOLDER"
APPLICANTS_PER_PAGE = 25 #change depending on preferences

# ---------------- SETUP ----------------

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

options = webdriver.ChromeOptions()
options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
options.add_argument(f"--profile-directory={PROFILE_NAME}")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--start-maximized")

options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_FOLDER,
    "download.prompt_for_download": False,
    "plugins.always_open_pdf_externally": True,
})

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options,
)
wait = WebDriverWait(driver, 15)

# ---------------- HELPERS ----------------

def get_page_applicant_urls():
    links = driver.find_elements(By.XPATH, "//a[contains(@href,'applicationId')]")
    seen_ids = set()
    urls = []
    for link in links:
        href = link.get_attribute("href") or ""
        match = re.search(r'applicationId=(\d+)', href)
        if match:
            app_id = match.group(1)
            if app_id not in seen_ids:
                seen_ids.add(app_id)
                urls.append(href)
    return urls


def find_clickable(xpaths, timeout=6):
    for xpath in xpaths:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
        except TimeoutException:
            continue
    return None


def save_via_requests(pdf_url, filename):
    """Download PDF using requests with the browser's session cookies."""
    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent"),
        "Referer": "https://www.linkedin.com/",
    }
    try:
        resp = requests.get(pdf_url, cookies=cookies, headers=headers,
                            allow_redirects=True, timeout=30)
        if resp.status_code == 200:
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            with open(filepath, "wb") as f:
                f.write(resp.content)
            print(f"    Saved: {filename} ({len(resp.content) // 1024} KB)")
            return True
        else:
            print(f"    HTTP {resp.status_code} — skipping")
            return False
    except Exception as e:
        print(f"    Request error: {e}")
        return False


def get_pdf_url_from_new_tab(tabs_before):
    """Wait for a new tab to appear, grab its URL, close it."""
    original = driver.current_window_handle
    for _ in range(20):  # up to 10 seconds
        time.sleep(0.5)
        new_tabs = set(driver.window_handles) - tabs_before
        if new_tabs:
            break
    else:
        return None

    new_tab = new_tabs.pop()
    driver.switch_to.window(new_tab)
    time.sleep(2)
    pdf_url = driver.current_url
    driver.close()
    driver.switch_to.window(original)
    return pdf_url


def download_resume(applicant_num):
    # Try download button directly first
    download_btn = find_clickable([
        "//button[.//*[@id='download-small']]",
        "//button[.//span[normalize-space(text())='Download']]",
    ], timeout=5)

    if download_btn is None:
        print("  Clicking Resume tab...")
        resume_tab = find_clickable([
            "//a[.//*[@id='document-small']]",
            "//a[.//span[normalize-space(text())='Resume']]",
        ], timeout=8)
        if resume_tab:
            resume_tab.click()
            time.sleep(5)

        download_btn = find_clickable([
            "//button[.//*[@id='download-small']]",
            "//button[.//span[normalize-space(text())='Download']]",
        ], timeout=12)

    if download_btn is None:
        print("  No download button found — skipping")
        return False

    print("  Clicking Download...")
    tabs_before = set(driver.window_handles)  # capture BEFORE the click
    download_btn.click()

    pdf_url = get_pdf_url_from_new_tab(tabs_before)
    if not pdf_url:
        print(f"  Unexpected URL: {pdf_url} — skipping")
        return False

    print(f"  PDF URL: {pdf_url[:80]}")
    filename = f"resume_{applicant_num:03d}.pdf"
    return save_via_requests(pdf_url, filename)


# ---------------- SCRAPER ----------------

def scrape_resumes():
    print("Opening LinkedIn applicants page...")
    driver.get(JOB_URL)
    time.sleep(5)

    if "login" in driver.current_url or "authwall" in driver.current_url:
        print("\nLinkedIn login required.")
        input("Log in in the Chrome window, then press Enter here...")
        driver.get(JOB_URL)
        time.sleep(6)

    # Phase 1: collect all applicant URLs
    all_urls = []
    page = 0

    while True:
        print(f"\nCollecting page {page + 1}...")
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//a[contains(@href,'applicationId')]")
            ))
        except TimeoutException:
            print("No more applicants found.")
            break

        page_urls = get_page_applicant_urls()
        print(f"  {len(page_urls)} applicants")

        if not page_urls:
            break

        all_urls.extend(page_urls)

        if len(page_urls) < APPLICANTS_PER_PAGE:
            break

        base = JOB_URL.split("&start=")[0]
        driver.get(f"{base}&start={(page + 1) * APPLICANTS_PER_PAGE}")
        time.sleep(6)
        page += 1

    print(f"\nTotal applicants: {len(all_urls)}")

    # Phase 2: download each resume
    success = 0
    for i, url in enumerate(all_urls):
        print(f"\nApplicant {i + 1}/{len(all_urls)}")
        try:
            driver.get(url)
            time.sleep(5)
            if download_resume(i + 1):
                success += 1
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(8)

    print(f"\nDone. Saved {success}/{len(all_urls)} resumes to {DOWNLOAD_FOLDER}")


# ---------------- RUN ----------------

try:
    scrape_resumes()
finally:
    driver.quit()

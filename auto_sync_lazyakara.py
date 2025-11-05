import os
import re
import time as pytime
import requests
from datetime import datetime, date, timedelta, timezone
from github import Github, GithubException

# =============== KONFIGURASI ===============
GITHUB_TOKEN = os.getenv("GITHUB_PAT")
SOURCE_URL   = "https://raw.githubusercontent.com/Xaffin/-/refs/heads/main/%E0%B8%AD%E0%B8%B1%E0%B8%9F%E0%B8%9F%E0%B8%B4%E0%B8%99"
TARGET_REPO  = "Akara4579/Lazyakara"
GIT_BRANCH   = "main"
COMMIT_MSG   = "Auto update: Sync playlist from source + footer update"
SLEEP_BETWEEN_COMMITS_SEC = 0.7

EXPIRE_HOUR_LOCAL = 13
EXPIRE_MINUTE_LOCAL = 0
SYNC_DISABLED_MARKER = ".SYNC_DISABLED"

# =============== WIB ===============
JAKARTA_TZ = timezone(timedelta(hours=7))

def now_jakarta() -> datetime:
    return datetime.now(tz=JAKARTA_TZ)

def expiry_cutoff(dt: date) -> datetime:
    return datetime(dt.year, dt.month, dt.day, EXPIRE_HOUR_LOCAL, EXPIRE_MINUTE_LOCAL, tzinfo=JAKARTA_TZ)

# =============== PARSER TANGGAL ===============
ID_MONTHS = {
    "JAN": 1, "JANUARI": 1,
    "FEB": 2, "FEBRUARI": 2,
    "MAR": 3, "MARET": 3,
    "APR": 4, "APRIL": 4,
    "MEI": 5,
    "JUN": 6, "JUNI": 6,
    "JUL": 7, "JULI": 7,
    "AGU": 8, "AGUSTUS": 8,
    "SEP": 9, "SEPTEMBER": 9,
    "OKT": 10, "OKTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DES": 12, "DESEMBER": 12,
}

def parse_date_from_name(name: str) -> date | None:
    name = name.upper()
    m = re.search(r'(\d{1,2})([A-Z]+)(\d{4})', name)
    if not m:
        return None
    dd = int(m.group(1))
    bulan_str = m.group(2)
    yyyy = int(m.group(3))
    # Cari bulan
    for k, v in ID_MONTHS.items():
        if bulan_str.startswith(k):
            try:
                return date(yyyy, v, dd)
            except ValueError:
                return None
    return None

def is_expired_by_name(name: str) -> bool:
    dt = parse_date_from_name(name)
    if not dt:
        print(f"⚠️ Tidak bisa baca tanggal dari {name}")
        return False
    cutoff = expiry_cutoff(dt)
    now_ = now_jakarta()
    print(f"ℹ️ File {name} => cutoff {cutoff}, now {now_}")
    return now_ >= cutoff

# =============== FOOTER ===============
FOOTER_REGEX = r'(?mi)^\s*#EXTM3U\s+billed-msg="[^"]+"\s*$'

def strip_footer(text: str) -> str:
    return re.sub(FOOTER_REGEX, '', text).strip()

def add_footer(text: str, filename: str, expired: bool) -> str:
    billed = "MASA BERLAKU HABIS| lynk.id/magelife😎" if expired else f"😎{filename}| lynk.id/magelife😎"
    return f"{strip_footer(text)}\n\n#EXTM3U billed-msg=\"{billed}\"\n"

def expired_block() -> str:
    return (
        "#EXTINF:-1 group-logo=\"https://i.imgur.com/aVBedkE.jpeg\",🔰 MAGELIFE OFFICIAL\n"
        "#EXTINF:-1 tvg-name=\"Expired\", MASA BERLAKU HABIS\n"
        "https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n"
    )

# =============== SYNC CORE ===============
def get_source_content() -> str | None:
    try:
        print(f"📡 Mengambil konten dari {SOURCE_URL}")
        r = requests.get(SOURCE_URL, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"❌ Gagal ambil sumber: {e}")
        return None

def repo_has_marker(repo) -> bool:
    try:
        repo.get_contents(SYNC_DISABLED_MARKER, ref=GIT_BRANCH)
        return True
    except GithubException:
        return False

def update_file(repo, name: str, base_text: str):
    expired = is_expired_by_name(name)
    content = expired_block() if expired else base_text
    new_content = add_footer(content, name, expired)

    try:
        contents = repo.get_contents(name, ref=GIT_BRANCH)
        old_text = contents.decoded_content.decode("utf-8")
        if strip_footer(old_text).strip() == strip_footer(new_content).strip():
            print(f"➡️ {name}: Tidak ada perubahan, skip.")
            return
        repo.update_file(name, COMMIT_MSG, new_content, contents.sha, branch=GIT_BRANCH)
        print(f"✅ {name}: Diperbarui.")
    except GithubException as e:
        if e.status == 404:
            repo.create_file(name, COMMIT_MSG, new_content, branch=GIT_BRANCH)
            print(f"🆕 {name}: Dibuat baru.")
        else:
            print(f"❌ Gagal update {name}: {e}")

# =============== MAIN ===============
def main():
    if not GITHUB_TOKEN:
        print("❌ Error: GITHUB_PAT belum diatur.")
        return
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(TARGET_REPO)

    if repo_has_marker(repo):
        print("⚠️ Marker .SYNC_DISABLED ditemukan, stop.")
        return

    base_src = get_source_content()
    if not base_src:
        return
    base_clean = strip_footer(base_src)

    # Ambil semua file di repo
    print(f"📂 Mengambil daftar file dari {TARGET_REPO}...")
    try:
        files = repo.get_contents("", ref=GIT_BRANCH)
    except GithubException as e:
        print(f"❌ Tidak bisa ambil daftar file: {e}")
        return

    for idx, f in enumerate(files, 1):
        if f.type != "file":
            continue
        print(f"\n({idx}) Proses {f.name}")
        update_file(repo, f.name, base_clean)
        pytime.sleep(SLEEP_BETWEEN_COMMITS_SEC)

    print("\n🎯 Semua file selesai di-sync.")

if __name__ == "__main__":
    main()

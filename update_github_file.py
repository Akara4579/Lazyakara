import os
import re
import time as pytime
import requests
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from github import Github, GithubException

# =================== KONFIGURASI ===================
GITHUB_TOKEN = os.getenv("GITHUB_PAT")

SOURCE_URL   = "https://raw.githubusercontent.com/Xaffin/-/refs/heads/main/%E0%B8%AD%E0%B8%B1%E0%B8%9F%E0%B8%9F%E0%B8%B4%E0%B8%99"
TARGET_REPO  = "Akara4579/Lazyakara"
GIT_BRANCH   = "main"

COMMIT_MSG   = "Auto update: Sync playlist from source + footer update"
SLEEP_BETWEEN_COMMITS_SEC = 0.7

EXPIRE_HOUR_LOCAL   = 13
EXPIRE_MINUTE_LOCAL = 0

SYNC_DISABLED_MARKER = ".SYNC_DISABLED"

# File yang pasti tidak boleh disentuh
SKIP_FILES = {
    "update_github_file.py",
    SYNC_DISABLED_MARKER,
}

# Kalau isi lama tidak tampak seperti playlist (#EXTM3U), jangan overwrite
FORCE_OVERWRITE_NON_PLAYLIST = False

# =================== WIB ===================
JAKARTA_TZ = timezone(timedelta(hours=7))

def now_jakarta() -> datetime:
    return datetime.now(tz=JAKARTA_TZ)

def expiry_cutoff(dt: date) -> datetime:
    return datetime(dt.year, dt.month, dt.day, EXPIRE_HOUR_LOCAL, EXPIRE_MINUTE_LOCAL, tzinfo=JAKARTA_TZ)

# =================== PARSER TANGGAL ===================
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

def parse_date_from_name(name: str) -> Optional[date]:
    upper = name.upper()
    m = re.search(r'(\d{1,2})([A-Z]+)(\d{4})', upper)
    if not m:
        return None
    dd = int(m.group(1))
    bulan_str = m.group(2)
    yyyy = int(m.group(3))
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
        print(f"⚠️  Tidak bisa baca tanggal dari '{name}' → dianggap belum kadaluarsa.")
        return False
    cutoff = expiry_cutoff(dt)
    now_ = now_jakarta()
    print(f"ℹ️  {name} → cutoff {cutoff.isoformat()} | now {now_.isoformat()}")
    return now_ >= cutoff

# =================== FOOTER / PESAN ===================
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

# =================== SYNC CORE ===================
def get_source_content() -> Optional[str]:
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

def looks_like_playlist(text: str) -> bool:
    return "#EXTM3U" in text.upper()

def update_file(repo, name: str, base_text: str):
    """
    Update satu file:
      - expired → pakai expired_block() + footer
      - belum expired → pakai base_text + footer
      - skip file pada SKIP_FILES
      - jangan overwrite file non-playlist (tanpa #EXTM3U) kecuali FORCE_OVERWRITE_NON_PLAYLIST=True
    """
    if name in SKIP_FILES:
        print(f"⏭️  {name}: Masuk daftar pengecualian, skip.")
        return

    expired = is_expired_by_name(name)
    content_body = expired_block() if expired else base_text
    new_content = add_footer(content_body, name, expired)

    try:
        contents = repo.get_contents(name, ref=GIT_BRANCH)
        old_text = contents.decoded_content.decode("utf-8")

        if not looks_like_playlist(old_text) and not FORCE_OVERWRITE_NON_PLAYLIST:
            print(f"⏭️  {name}: File lama tidak terdeteksi sebagai playlist (#EXTM3U), skip.")
            return

        # Bandingkan FULL content agar perubahan footer/status tidak di-skip
        if old_text.strip() == new_content.strip():
            print(f"➡️  {name}: Tidak ada perubahan, skip.")
            return

        repo.update_file(name, COMMIT_MSG, new_content, contents.sha, branch=GIT_BRANCH)
        print(f"✅  {name}: Diperbarui.")
    except GithubException as e:
        if e.status == 404:
            repo.create_file(name, COMMIT_MSG, new_content, branch=GIT_BRANCH)
            print(f"🆕  {name}: Dibuat baru.")
        else:
            print(f"❌  {name}: Gagal update → {e}")

def main():
    if not GITHUB_TOKEN:
        print("❌ Error: GITHUB_PAT belum diatur di environment.")
        return

    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(TARGET_REPO)

    if repo_has_marker(repo):
        print("⚠️  Marker .SYNC_DISABLED ditemukan, proses dihentikan.")
        return

    base_src = get_source_content()
    if not base_src:
        return
    base_clean = strip_footer(base_src)

    print(f"📂 Mengambil daftar file dari {TARGET_REPO}@{GIT_BRANCH} ...")
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

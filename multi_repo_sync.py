import os
import re
import time as pytime
import requests
import calendar
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional
from github import Github, GithubException

# ==========================
# KONFIGURASI VIA ENV
# ==========================
GITHUB_TOKEN = os.getenv("GITHUB_PAT")  # WAJIB: isi dari Secrets/Actions
# Sumber konten (tanpa footer). Kita akan tambahkan footer di sini
SOURCE_URL   = os.getenv("SOURCE_URL", "https://raw.githubusercontent.com/Xaffin/-/refs/heads/main/%E0%B8%AD%E0%B8%B1%E0%B8%9F%E0%B8%9F%E0%B8%B4%E0%B8%99")

# MODE TARGET REPO:
#   1) REPOS_CSV: daftar "owner/repo" dipisah koma (paling disarankan untuk presisi)
#   2) SINGLE_REPO: satu repo "owner/repo"
#   3) OWNER_ALL_REPOS: isi OWNER, akan sync SEMUA repo milik owner (hati-hati!)
REPOS_CSV      = os.getenv("REPOS_CSV", "")           # contoh: "Akara4579/Lazyakara,uppermoon77/cdguntee"
SINGLE_REPO    = os.getenv("SINGLE_REPO", "Akara4579/Lazyakara")
OWNER_ALL_REPOS = os.getenv("OWNER_ALL_REPOS", "")    # contoh: "Akara4579" (akan sync semua repo milik owner ini)

# Branch & commit
GIT_BRANCH    = os.getenv("GIT_BRANCH", "main")
COMMIT_MSG    = os.getenv("COMMIT_MSG", "Auto update: Sync playlist from source + footer update (multi-repo)")
SLEEP_BETWEEN_COMMITS_SEC = float(os.getenv("SLEEP_BETWEEN_COMMITS_SEC", "0.7"))
SLEEP_BETWEEN_REPOS_SEC   = float(os.getenv("SLEEP_BETWEEN_REPOS_SEC", "1.0"))

# Expired rules (per FILE NAME)
EXPIRE_HOUR_LOCAL   = int(os.getenv("EXPIRE_HOUR_LOCAL", "13"))  # 13:00 WIB
EXPIRE_MINUTE_LOCAL = int(os.getenv("EXPIRE_MINUTE_LOCAL", "0"))

# Marker global per-repo (opsional)
SYNC_DISABLED_MARKER = ".SYNC_DISABLED"
# True = jika marker ada, SEMUA file dipaksa expired walau belum jamnya
# False = abaikan marker sampai lewat cutoff masing-masing file
HONOR_MARKER_EVEN_BEFORE_EXPIRY = os.getenv("HONOR_MARKER_EVEN_BEFORE_EXPIRY", "false").lower() == "true"

# Target file generator (bisa diubah via ENV)
MONTH_NAME = os.getenv("MONTH_NAME", "NOVEMBER")  # contoh: "NOVEMBER"
YEAR       = int(os.getenv("YEAR", "2025"))       # contoh: 2025
PREFIX     = os.getenv("PREFIX", "CD")            # contoh: "CD"

# ==========================
# UTIL TANGGAL & WIB
# ==========================
JAKARTA_TZ = timezone(timedelta(hours=7))

def now_jakarta() -> datetime:
    return datetime.now(tz=JAKARTA_TZ)

def expiry_cutoff(dt: date) -> datetime:
    return datetime(dt.year, dt.month, dt.day, EXPIRE_HOUR_LOCAL, EXPIRE_MINUTE_LOCAL, tzinfo=JAKARTA_TZ)

# ==========================
# PARSER TANGGAL DARI NAMA (FILE)
# ==========================
ID_MONTHS = {
    "JANUARI": 1, "FEBRUARI": 2, "MARET": 3, "APRIL": 4, "MEI": 5, "JUNI": 6,
    "JULI": 7, "AGUSTUS": 8, "SEPTEMBER": 9, "OKTOBER": 10, "NOVEMBER": 11, "DESEMBER": 12
}

def parse_date_from_name(name: str) -> Optional[date]:
    """
    Deteksi tanggal dari nama file:
    - DD<BULAN_ID>YYYY (mis. 21NOVEMBER2025, CD21OKTOBER2025)
    - DD[-_./]MM[-_./]YYYY
    - YYYY[-_./]MM[-_./]DD
    - 8 digit rapat: YYYYMMDD atau DDMMYYYY
    """
    name_u = name.upper()

    m = re.search(r'(\d{1,2})(JANUARI|FEBRUARI|MARET|APRIL|MEI|JUNI|JULI|AGUSTUS|SEPTEMBER|OKTOBER|NOVEMBER|DESEMBER)(\d{4})', name_u)
    if m:
        dd = int(m.group(1)); mm = ID_MONTHS[m.group(2).upper()]; yyyy = int(m.group(3))
        try: return date(yyyy, mm, dd)
        except ValueError: pass

    m = re.search(r'(\d{1,2})[-_./](\d{1,2})[-_./](\d{4})', name_u)
    if m:
        dd = int(m.group(1)); mm = int(m.group(2)); yyyy = int(m.group(3))
        try: return date(yyyy, mm, dd)
        except ValueError: pass

    m = re.search(r'(\d{4})[-_./](\d{1,2})[-_./](\d{1,2})', name_u)
    if m:
        yyyy = int(m.group(1)); mm = int(m.group(2)); dd = int(m.group(3))
        try: return date(yyyy, mm, dd)
        except ValueError: pass

    m = re.search(r'(\d{8})', name_u)
    if m:
        digits = m.group(1)
        try:
            yyyy = int(digits[0:4]); mm = int(digits[4:6]); dd = int(digits[6:8])
            return date(yyyy, mm, dd)
        except ValueError:
            pass
        try:
            dd  = int(digits[0:2]); mm = int(digits[2:4]); yyyy = int(digits[4:8])
            return date(yyyy, mm, dd)
        except ValueError:
            pass

    return None

def is_expired_by_name(name: str) -> bool:
    dt = parse_date_from_name(name)
    if not dt:
        print(f"⚠️  Tidak menemukan tanggal di nama '{name}'. Lewati expiry per-file.")
        return False
    cutoff = expiry_cutoff(dt)
    now_ = now_jakarta()
    print(f"ℹ️  File date = {dt.isoformat()} | Cutoff = {cutoff.isoformat()} | Now = {now_.isoformat()}")
    return now_ >= cutoff

# ==========================
# FOOTER & TEMPLATE
# ==========================
FOOTER_REGEX = r'(?mi)^\s*#EXTM3U\s+billed-msg="[^"]+"\s*$'

def generate_footer(dest_file_path: str, expired: bool) -> str:
    if expired:
        return '#EXTM3U billed-msg="MASA BERLAKU HABIS| lynk.id/magelife😎"'
    return f'#EXTM3U billed-msg="😎{dest_file_path}| lynk.id/magelife😎"'

def strip_footer(text: str) -> str:
    return re.sub(FOOTER_REGEX, "", text).strip()

def add_footer(text: str, dest_file_path: str, expired: bool) -> str:
    cleaned = strip_footer(text)
    return f"{cleaned}\n\n{generate_footer(dest_file_path, expired)}\n"

def build_expired_playlist_block() -> str:
    return (
        '#EXTINF:-1 group-logo="https://i.imgur.com/aVBedkE.jpeg",🔰 MAGELIFE OFFICIAL\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/CctbVah.jpeg" group-title="🔰 MAGELIFE OFFICIAL", MASA BERLAKU HABIS\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/XXQ2pQ3.jpeg", ❌ MASA BERLAKU HABIS\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/XXQ2pQ3.jpeg" group-title="❌ MASA BERLAKU HABIS", MASA BERLAKU HABIS\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/XXQ2pQ3.jpeg", ❌ MASA BERLAKU HABIS OM\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/XXQ2pQ3.jpeg" group-title="❌ MASA BERLAKU HABIS OM", MASA BERLAKU HABIS\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/XXQ2pQ3.jpeg", ❌ MASA BERLAKU HABIS TANTE\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/XXQ2pQ3.jpeg" group-title="❌ MASA BERLAKU HABIS TANTE", MASA BERLAKU HABIS\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/bjfYe6g.jpeg", ✅ SILAHKAN RE ORDER\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/bjfYe6g.jpeg" group-title="✅ SILAHKAN RE ORDER", SILAHKAN RE ORDER\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/bjfYe6g.jpeg", ✅SILAHKAN RE ORDER OM\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/bjfYe6g.jpeg" group-title="✅ SILAHKAN RE ORDER OM", SILAHKAN RE ORDER\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/bjfYe6g.jpeg", ✅SILAHKAN RE ORDER TANTE\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/bjfYe6g.jpeg" group-title="✅ SILAHKAN RE ORDER TANTE", SILAHKAN RE ORDER\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/bjfYe6g.jpeg", 📲 Wa 082219213334\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/bjfYe6g.jpeg" group-title="📲 Wa 082219213334", SILAHKAN RE ORDER\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/bjfYe6g.jpeg", 📲 Wa 082219213334 order\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/bjfYe6g.jpeg" group-title="📲 Wa 082219213334 order", SILAHKAN RE ORDER\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/PJ9tRpK.jpeg",✅ ORDER LYNK\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/PJ9tRpK.jpeg" group-title="✅ ORDER LYNK", ORDER LYNK\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/PJ9tRpK.jpeg",✅ https://lynk.id/magelife\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/PJ9tRpK.jpeg" group-title="✅ https://lynk.id/magelife", ORDER SHOPEE\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/PJ9tRpK.jpeg", ✅ORDER SHOPEE \n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/EWttwBZ.jpeg" group-title="✅ ORDER SHOPEE", ORDER LYNK\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n\n'
        '#EXTINF:-1 group-logo="https://i.imgur.com/PJ9tRpK.jpeg", ✅ https://shorturl.at/1r9BB\n\n'
        '#EXTINF:-1 tvg-id="Iheart80s" tvg-name="Iheart80s" tvg-logo="https://i.imgur.com/EWttwBZ.jpeg" group-title="✅ https://shorturl.at/1r9BB", ORDER LYNK\n'
        'https://iheart-iheart80s-1-us.roku.wurl.tv/playlist.m3u8\n'
    )

# ==========================
# AMBIL KONTEN SUMBER (sekali ambil)
# ==========================
def get_source_content() -> Optional[str]:
    try:
        print(f"Mengambil konten dari: {SOURCE_URL} ...")
        headers = {"User-Agent": "MagelifeSync/2.0 (+https://lynk.id/magelife)"}
        r = requests.get(SOURCE_URL, timeout=30, headers=headers)
        r.raise_for_status()
        print("✅ Konten berhasil diambil.")
        return r.text
    except requests.exceptions.RequestException as e:
        print(f"❌ Gagal mengambil konten sumber: {e}")
        return None

# ==========================
# GITHUB HELPERS
# ==========================
def ensure_marker(repo):
    try:
        repo.get_contents(SYNC_DISABLED_MARKER, ref=GIT_BRANCH)
        print(f"ℹ️  Marker {SYNC_DISABLED_MARKER} sudah ada.")
    except GithubException as e:
        if getattr(e, "status", None) == 404:
            print(f"📝 Membuat marker {SYNC_DISABLED_MARKER} ...")
            repo.create_file(
                path=SYNC_DISABLED_MARKER,
                message="Mark: sync disabled (manual/opsional)",
                content=f"Marked at {now_jakarta().isoformat()} WIB\n",
                branch=GIT_BRANCH
            )
            print("✅ Marker dibuat.")
        else:
            print(f"⚠️  Tidak bisa cek/buat marker: {e}")

def repo_has_marker(repo) -> bool:
    try:
        repo.get_contents(SYNC_DISABLED_MARKER, ref=GIT_BRANCH)
        return True
    except GithubException:
        return False

# ==========================
# TARGET FILES (dinamis per bulan/tahun)
# ==========================
def generate_target_files(month_name: str, year: int, prefix: str) -> List[str]:
    mname = month_name.upper()
    if mname not in ID_MONTHS:
        raise ValueError(f"Bulan '{month_name}' tidak dikenal. Gunakan salah satu: {', '.join(ID_MONTHS.keys())}")
    mnum = ID_MONTHS[mname]
    days_in_month = calendar.monthrange(year, mnum)[1]
    return [f"{prefix}{day:02d}{mname}{year}" for day in range(1, days_in_month + 1)]

# ==========================
# UPDATE PER FILE
# ==========================
def update_single_file(g: Github, full_repo_name: str, dest_file_path: str, base_content_no_footer: str, force_expired: Optional[bool] = None) -> None:
    repo = g.get_repo(full_repo_name)
    expired_now = is_expired_by_name(dest_file_path) if force_expired is None else force_expired
    content_body = build_expired_playlist_block() if expired_now else base_content_no_footer
    new_content_with_footer = add_footer(content_body, dest_file_path, expired_now)

    print(f"\n🟦 [{full_repo_name}] Memproses file: {dest_file_path} (expired={expired_now})")
    try:
        contents = repo.get_contents(dest_file_path, ref=GIT_BRANCH)
        sha = contents.sha
        old_text = contents.decoded_content.decode("utf-8")
        old_no_footer = strip_footer(old_text)
        if old_no_footer.strip() == content_body.strip():
            print("➡️  Tidak ada perubahan, skip.")
            return
        print("✏️  Ada perubahan, memperbarui file...")
        repo.update_file(
            path=contents.path,
            message=COMMIT_MSG,
            content=new_content_with_footer,
            sha=sha,
            branch=GIT_BRANCH
        )
        print("✅ File berhasil di-update!")
    except GithubException as e:
        if getattr(e, "status", None) == 404:
            print("🆕 File belum ada, membuat baru...")
            repo.create_file(
                path=dest_file_path,
                message=COMMIT_MSG,
                content=new_content_with_footer,
                branch=GIT_BRANCH
            )
            print("✅ File baru berhasil dibuat.")
        else:
            print(f"❌ Error API GitHub: {e}")
    except Exception as e:
        print(f"❌ Error tak terduga: {e}")

# ==========================
# RESOLVER DAFTAR REPO
# ==========================
def resolve_target_repos(g: Github) -> List[str]:
    repos = []

    # 1) REPOS_CSV eksplisit
    if REPOS_CSV.strip():
        for item in REPOS_CSV.split(","):
            name = item.strip()
            if name:
                repos.append(name)

    # 2) SINGLE_REPO (fallback kalau REPOS_CSV kosong)
    elif SINGLE_REPO.strip():
        repos.append(SINGLE_REPO.strip())

    # 3) OWNER_ALL_REPOS (opsional, hati-hati)
    if OWNER_ALL_REPOS.strip():
        owner = OWNER_ALL_REPOS.strip()
        print(f"🔎 Mengambil semua repo milik owner '{owner}' ...")
        try:
            user = g.get_user(owner)
            for r in user.get_repos():  # termasuk private jika token punya akses
                repos.append(r.full_name)
        except GithubException:
            try:
                org = g.get_organization(owner)
                for r in org.get_repos():
                    repos.append(r.full_name)
            except GithubException as e:
                print(f"⚠️  Gagal mengambil repo untuk owner '{owner}': {e}")

    # deduplicate sambil preserve order
    seen = set()
    uniq = []
    for r in repos:
        if r not in seen:
            uniq.append(r)
            seen.add(r)
    return uniq

# ==========================
# MAIN
# ==========================
def main():
    if not GITHUB_TOKEN:
        print("❌ Error: environment variable GITHUB_PAT belum diatur.")
        return

    g = Github(GITHUB_TOKEN)

    # Ambil konten sumber sekali saja
    src = get_source_content()
    if src is None:
        print("❌ Gagal ambil sumber. Stop.")
        return
    base_no_footer = strip_footer(src)

    # Resolve daftar repo yang akan diproses
    target_repos = resolve_target_repos(g)
    if not target_repos:
        print("❌ Tidak ada target repository yang akan diproses.")
        return

    # Siapkan daftar file target
    try:
        target_files = generate_target_files(MONTH_NAME, YEAR, PREFIX)
    except ValueError as e:
        print(f"❌ Konfigurasi target files error: {e}")
        return

    print(f"\n📦 Total repository: {len(target_repos)}")
    for idx_repo, full_repo_name in enumerate(target_repos, start=1):
        print(f"\n================= REPO {idx_repo}/{len(target_repos)}: {full_repo_name} =================")
        try:
            repo = g.get_repo(full_repo_name)
        except GithubException as e:
            print(f"⚠️  Tidak bisa akses {full_repo_name}: {e}")
            continue

        force_expired: Optional[bool] = None
        if HONOR_MARKER_EVEN_BEFORE_EXPIRY and repo_has_marker(repo):
            print(f"⛔ Ditemukan marker {SYNC_DISABLED_MARKER} di {full_repo_name}. Semua file dipaksa expired.")
            force_expired = True
        else:
            force_expired = None  # auto by filename cutoff

        print(f"📁 Daftar file target ({len(target_files)}): {target_files}")

        for i, dest_file_path in enumerate(target_files, start=1):
            print(f"\n({i}/{len(target_files)}) Update {dest_file_path} di {full_repo_name} ...")
            update_single_file(g, full_repo_name, dest_file_path, base_no_footer, force_expired=force_expired)
            pytime.sleep(SLEEP_BETWEEN_COMMITS_SEC)

        print(f"✅ Selesai untuk repo {full_repo_name}.")
        pytime.sleep(SLEEP_BETWEEN_REPOS_SEC)

    print("\n🎯 Semua repository selesai diproses!")

if __name__ == "__main__":
    main()

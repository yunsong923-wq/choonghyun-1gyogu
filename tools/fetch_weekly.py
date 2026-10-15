#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
주간충현 사본 만들기 프로그램
=====================================================================
하는 일 (순서대로)
  1. 구글 시트 '홈' 탭의 '주간충현 번호' 칸에서 이번 호 번호를 읽어 옵니다. (예: 1271)
  2. 주간충현 웹진 페이지(http://webzine.choonghyunchurch.or.kr/번호)에서 쪽 이미지 주소를 찾습니다.
  3. 쪽 이미지(8장 정도)를 내려받아 휴대폰에서 빨리 뜨도록 크기를 줄여 weekly/img/ 폴더에 저장합니다.
  4. weekly/data.json 에 "이번 호는 몇 호, 제목, 쪽 목록"을 기록합니다. (보기 화면이 이 파일을 읽습니다)

  ★ 새 호 자동 찾기: 시트 번호(또는 이미 받아 둔 호)보다 큰 번호를 웹진에서 차례로 찾아보고,
     실제로 쪽 이미지가 있는 가장 큰 번호를 이번 호로 정합니다. 그래서 시트의 번호를 안 바꿔도 새 호가 올라오면 자동으로 받습니다.
     (번호가 1씩 늘지 않아도 몇 칸 건너뛴 번호까지 찾아봅니다. 아래 SEARCH_AHEAD 참고)

이 프로그램은 GitHub 서버가 자동으로 실행합니다. 직접 만질 일은 거의 없습니다.
  · 이미 받아 둔 호이면 아무것도 하지 않고 끝납니다.
  · 웹진에 아직 새 호가 올라오지 않았으면 기존 사본을 그대로 두고 끝납니다. (다음 실행 때 다시 시도)
  · 받는 도중에 하나라도 실패하면 기존 사본은 절대 지우지 않습니다.
=====================================================================
"""
import csv
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from PIL import Image

# ─────────────────────────────────────────────────────────────
# ① 설정값 (필요할 때만 바꾸세요)
# ─────────────────────────────────────────────────────────────
SHEET_ID = "1mtOZ3dZe3HGevEOO--vNNKdrvKFadMLSNslzjuzO_3Q"   # 구글 시트 주소 중간의 긴 번호 (앱의 SHEET_ID 와 같아야 합니다)
SHEET_TAB = "홈"                                              # 번호가 적힌 시트 탭 이름
SHEET_LABEL = "주간충현 번호"                                  # 시트 왼쪽 칸에 적힌 항목 이름 (글자가 정확히 같아야 합니다)
WEBZINE_BASE = os.environ.get("WEBZINE_BASE", "http://webzine.choonghyunchurch.or.kr/")  # 웹진 주소 앞부분 (끝 번호는 뒤에 붙입니다)
ALLOWED_HOST = os.environ.get("ALLOWED_HOST", "choonghyunchurch.or.kr")  # 이 사이트 이미지만 받습니다 (안전장치 — 수정 금지)
MAX_WIDTH = 1400        # 이미지 가로 크기 상한(픽셀). 이보다 크면 줄입니다. 휴대폰에서는 이 정도면 충분합니다
JPEG_QUALITY = 82       # 사진 품질(1~100). 낮출수록 파일이 작아지고 흐려집니다
MAX_IMAGE_BYTES = 20 * 1024 * 1024   # 이미지 한 장의 최대 크기(20MB). 넘으면 이상한 파일로 보고 받지 않습니다 — 수정 금지
AUTO_FIND = os.environ.get("AUTO_FIND", "yes").strip().lower() != "no"   # yes = 새 호를 자동으로 찾기 / no 로 바꾸면 예전처럼 시트의 번호만 사용
SEARCH_AHEAD = int(os.environ.get("SEARCH_AHEAD", "8"))   # 지금 호 번호보다 몇 번 앞까지 찾아볼지 (8이면 +1 ~ +8). 번호가 건너뛰어도 찾게 하려는 여유분입니다
HTTP_TIMEOUT = 40       # 한 번 요청을 기다리는 최대 시간(초)
RETRIES = 4             # 실패하면 다시 시도하는 횟수

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 저장소 맨 위 폴더
WEEKLY_DIR = os.path.join(ROOT, "weekly")
IMG_DIR = os.path.join(WEEKLY_DIR, "img")
DATA_JSON = os.path.join(WEEKLY_DIR, "data.json")

HEADERS = {  # 웹진 서버가 사람이 쓰는 브라우저로 알아보게 하는 설정 (컴퓨터용 크롬으로 접속)
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
}
MOBILE_UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"  # 컴퓨터용으로 안 될 때 휴대폰용으로도 시도


def log(msg):
    print(msg, flush=True)


def http_get(url, **kw):
    """주소에서 내용을 받아 옵니다. 실패하면 잠시 쉬었다가 몇 번 더 시도합니다."""
    last = None
    for i in range(1, RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT, **kw)
            if r.status_code == 200:
                return r
            last = "HTTP %s" % r.status_code
            if r.status_code in (404, 410):   # 없는 페이지는 다시 해도 소용없음
                break
        except requests.RequestException as e:
            last = "%s: %s" % (type(e).__name__, e)
        log("  … 다시 시도 (%d/%d) %s" % (i, RETRIES, last))
        time.sleep(3 * i)
    raise RuntimeError("받기 실패: %s (%s)" % (url, last))


# ─────────────────────────────────────────────────────────────
# ② 이번 호 번호 알아내기
# ─────────────────────────────────────────────────────────────
def parse_number_from_csv(text):
    """시트에서 내려받은 글(CSV)에서 '주간충현 번호' 줄의 숫자를 찾습니다. 없으면 None."""
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[0].strip() == SHEET_LABEL:
            m = re.search(r"(\d+)\s*$", row[1].strip())
            if m:
                return m.group(1)
    return None


def get_number():
    """번호를 정하는 순서: ① 직접 지정(WEEKLY_NUMBER) → ② 구글 시트"""
    forced = os.environ.get("WEEKLY_NUMBER", "").strip()
    if forced:
        m = re.search(r"(\d+)\s*$", forced)
        if m:
            log("번호를 직접 지정받았습니다: %s" % m.group(1))
            return m.group(1)
    url = ("https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&headers=1&sheet=%s"
           % (SHEET_ID, urllib.parse.quote(SHEET_TAB)))
    r = http_get(url)
    r.encoding = "utf-8"
    num = parse_number_from_csv(r.text)
    if not num:
        raise RuntimeError("시트 '%s' 탭에서 '%s' 줄을 찾지 못했습니다. 시트를 확인하세요." % (SHEET_TAB, SHEET_LABEL))
    log("시트에서 읽은 번호: %s" % num)
    return num


# ─────────────────────────────────────────────────────────────
# ③ 웹진 페이지에서 쪽 이미지 주소 찾기
# ─────────────────────────────────────────────────────────────
def find_pages(html):
    """웹진 페이지 소스 안의 listImageArray[1] = '주소'; 줄들을 찾아 쪽 순서대로 돌려줍니다."""
    found = {}
    for idx, url in re.findall(r"listImageArray\[(\d+)\]\s*=\s*['\"]([^'\"]+)['\"]", html):
        found[int(idx)] = url.strip()
    if not found:   # 위 방법이 안 되면 'saveDir/webzine/호/p숫자.jpg' 모양의 주소를 모두 찾아 순서대로 사용
        loose = re.findall(r"https?://[^\s'\"<>)]+/saveDir/webzine/[^\s'\"<>)]+?\.(?:jpg|jpeg|png)", html, re.I)
        seen = []
        for u in loose:
            if u not in seen:
                seen.append(u)
        return seen
    return [found[k] for k in sorted(found)]


def find_title(html, number):
    m = re.search(r"<title>\s*(.*?)\s*</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else "주간충현 %s" % number


def safe_image_url(url):
    """받아도 되는 주소인지 검사합니다. 충현교회 사이트의 웹진 이미지(http/https)만 허용합니다."""
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    ok_host = host == ALLOWED_HOST or host.endswith("." + ALLOWED_HOST)
    return p.scheme in ("http", "https") and ok_host and "/saveDir/webzine/" in p.path


# ─────────────────────────────────────────────────────────────
# ④ 이미지 받아서 줄여 저장하기
# ─────────────────────────────────────────────────────────────
def download_and_shrink(url, dest):
    r = http_get(url, stream=True)
    buf = io.BytesIO()
    for chunk in r.iter_content(65536):
        buf.write(chunk)
        if buf.tell() > MAX_IMAGE_BYTES:
            raise RuntimeError("이미지가 너무 큽니다: %s" % url)
    buf.seek(0)
    im = Image.open(buf)
    im.load()                       # 진짜 이미지인지 끝까지 읽어서 확인
    if im.mode != "RGB":
        im = im.convert("RGB")
    if im.width > MAX_WIDTH:        # 너무 크면 가로 기준으로 줄임
        h = round(im.height * MAX_WIDTH / im.width)
        im = im.resize((MAX_WIDTH, h), Image.LANCZOS)
    im.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return im.width, im.height


def try_page(number):
    """웹진 번호 하나를 열어 보고, 쪽 이미지 목록이 실제로 있으면 (페이지 글, 주소)를 돌려줍니다. 없거나 접속이 안 되면 None.
    (새 호를 찾아볼 때 쓰는 가벼운 확인용입니다. 실패해도 오류로 멈추지 않고 '없음'으로 처리합니다)"""
    url = WEBZINE_BASE.rstrip("/") + "/" + str(number)
    for ua in (HEADERS["User-Agent"], MOBILE_UA):   # 컴퓨터용으로 안 되면 휴대폰용으로 한 번 더
        try:
            r = requests.get(url, headers=dict(HEADERS, **{"User-Agent": ua}), timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            log("  [찾기] %s번 접속 실패(%s) — 이번에는 건너뜁니다" % (number, type(e).__name__))
            return None
        if r.status_code != 200:   # 404 등: 아직 올라오지 않은 번호
            return None
        if len(find_pages(r.text)) >= 2:   # 쪽 이미지가 2장 이상이면 진짜 호로 인정
            return r.text, url
    return None


def find_newest(base):
    """base(지금 호 번호)보다 큰 번호를 base+1 ~ base+SEARCH_AHEAD 까지 보고, 진짜 호 중 가장 큰 번호를 돌려줍니다. 없으면 None."""
    best = None
    for n in range(base + 1, base + SEARCH_AHEAD + 1):
        got = try_page(n)
        if got:
            log("  [찾기] %d호 발견" % n)
            best = (n, got[0], got[1])
    return best


def read_current():
    try:
        with open(DATA_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    cur = read_current()
    prefetched = None   # 새 호를 찾으면서 이미 읽은 페이지 (다시 읽지 않도록 보관)

    forced = bool(os.environ.get("WEEKLY_NUMBER", "").strip())   # 직접 번호를 지정했는지 ('Run workflow' 에서 입력)
    try:
        number = get_number()   # 시트(또는 직접 지정)의 번호
    except Exception as e:      # 시트를 못 읽어도, 이미 받아 둔 호가 있으면 그 번호로 계속 진행
        if not cur.get("number"):
            raise
        log("시트 번호를 읽지 못해 지금 사본(%s호) 기준으로 진행합니다. (%s)" % (cur["number"], e))
        number = cur["number"]

    if AUTO_FIND and not forced and number.isdigit():
        base = int(number)
        if str(cur.get("number", "")).isdigit():
            base = max(base, int(cur["number"]))   # 시트 번호가 옛날 번호여도 이미 받은 호보다 뒤로 가지 않게 함
        log("새 호 찾는 중: %d호 다음 번호부터 %d개를 확인합니다" % (base, SEARCH_AHEAD))
        newest = find_newest(base)
        if newest:
            number, html0, url0 = str(newest[0]), newest[1], newest[2]
            prefetched = (html0, url0)
            log("→ 가장 새로운 호: %s호" % number)
        else:
            number = str(base)
            log("→ 새 호 없음. 현재 %s호를 유지합니다." % number)

    # 이미 같은 호를 받아 두었고 이미지도 다 있으면 할 일이 없음
    have_all = cur.get("number") == number and cur.get("pages") and all(
        os.path.exists(os.path.join(WEEKLY_DIR, p["src"])) for p in cur["pages"])
    if have_all and not os.environ.get("FORCE"):
        log("이미 %s호 사본이 있습니다. 할 일이 없습니다." % number)
        return 0

    page_url = WEBZINE_BASE.rstrip("/") + "/" + number
    log("웹진 페이지 읽는 중: %s" % page_url)
    try:
        if prefetched:   # 새 호를 찾으면서 이미 읽은 페이지가 있으면 그것을 사용
            class _Resp:   # 아래 진단 코드가 쓰는 모양에 맞춘 임시 틀 — 수정 금지
                url = prefetched[1]
                status_code = 200
                headers = {}
                text = prefetched[0]
            resp = _Resp()
        else:
            resp = http_get(page_url)
        html = resp.text
        if not find_pages(html):   # 컴퓨터용으로 목록이 없으면 휴대폰용 신분으로 한 번 더
            log("  컴퓨터용 접속에서 목록 없음 → 휴대폰용으로 다시 시도")
            r2 = requests.get(page_url, headers=dict(HEADERS, **{"User-Agent": MOBILE_UA}), timeout=HTTP_TIMEOUT)
            if find_pages(r2.text):
                resp, html = r2, r2.text
        if not find_pages(html):   # 그래도 없으면 원인 파악용으로 받은 내용을 보여 줌
            log("  [진단] 최종 주소: %s / 상태: %s / 글자 수: %d" % (resp.url, resp.status_code, len(html)))
            log("  [진단] 응답 헤더: %s" % dict(list(resp.headers.items())[:8]))
            log("  [진단] 내용 앞부분: %s" % re.sub(r"\s+", " ", html[:800]))
            log("  [진단] 'listImageArray' 글자 포함 여부: %s" % ("listImageArray" in html))
    except RuntimeError as e:
        if "HTTP 404" in str(e):   # 번호는 바꿨는데 웹진에 아직 안 올라온 경우
            log("아직 웹진에 %s호가 올라오지 않았습니다. 기존 사본을 그대로 둡니다. (%s)" % (number, e))
            return 0
        raise

    urls = find_pages(html)
    if not urls:
        log("이 페이지에서 쪽 이미지 목록을 찾지 못했습니다. 기존 사본을 그대로 둡니다.")
        log("(웹진 화면 구조가 바뀌었을 수 있습니다. 이 메시지가 계속 나오면 알려 주세요.)")
        return 1 if not cur else 0
    for u in urls:
        if not safe_image_url(u):
            raise RuntimeError("허용되지 않은 이미지 주소입니다: %s" % u)
    log("쪽 이미지 %d장 발견" % len(urls))

    # 임시 폴더에 먼저 다 받고, 전부 성공했을 때만 기존 사본과 바꿉니다 (중간 실패 시 기존 사본 보호)
    tmp = os.path.join(WEEKLY_DIR, "img_new")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    pages = []
    try:
        for i, u in enumerate(urls, 1):
            name = "p%d.jpg" % i
            w, h = download_and_shrink(u, os.path.join(tmp, name))
            size = os.path.getsize(os.path.join(tmp, name)) // 1024
            log("  %d쪽 저장: %dx%d, %dKB" % (i, w, h, size))
            pages.append({"src": "img/" + name, "w": w, "h": h})
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    shutil.rmtree(IMG_DIR, ignore_errors=True)
    os.replace(tmp, IMG_DIR)

    kst = timezone(timedelta(hours=9))
    data = {
        "number": number,
        "title": find_title(html, number),
        "pages": pages,
        "updated": datetime.now(kst).strftime("%Y-%m-%d %H:%M"),
        "source": page_url,
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log("완료: %s (%d쪽)" % (data["title"], len(pages)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("오류: %s" % e)
        sys.exit(1)

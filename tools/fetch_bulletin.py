#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
주보(주일예배 순서지) · 금요집회 순서지 사본 만들기 프로그램
=====================================================================
하는 일 (순서대로)
  1. 웹진(http://webzine.choonghyunchurch.or.kr/번호)의 번호들을 차례로 열어 봅니다.
  2. 페이지 제목을 보고 '주보' 인지 '금요집회' 인지 구별합니다. (주간충현 등 다른 글은 건너뜁니다)
  3. 각각 가장 새로운 것을 골라, 쪽 이미지를 내려받아 휴대폰에서 빨리 뜨도록 크기를 줄여
       sunday/img/  (주보),  friday/img/  (금요집회)  폴더에 저장합니다.
  4. sunday/data.json, friday/data.json 에 "몇 번, 제목, 쪽 목록"을 기록합니다.
     (보기 화면 sunday/index.html, friday/index.html 이 이 파일을 읽어 보여 줍니다)

이 프로그램은 GitHub 서버가 일주일에 한 번 자동으로 실행합니다. (.github/workflows/bulletin-copy.yml)
  · 새 것이 없으면 기존 사본을 그대로 두고 끝납니다.
  · 받는 도중에 하나라도 실패하면 기존 사본은 절대 지우지 않습니다.
  · 제목에 어떤 글자가 들어 있는지 몰라 구별이 안 될 때는, 번호를 직접 적어 한 번 실행하면 됩니다.
    (GitHub → Actions → '주보·금요집회 사본 만들기' → Run workflow → 번호 칸에 입력)
=====================================================================
"""
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import fetch_weekly as fw   # 주간충현 프로그램의 도구(웹진 읽기, 이미지 받아서 줄이기)를 빌려 씁니다

# ─────────────────────────────────────────────────────────────
# ① 설정값 (필요할 때만 바꾸세요)
# ─────────────────────────────────────────────────────────────
KINDS = [   # 받을 순서지 종류. key=내부 이름, name=화면 이름, dir=저장 폴더, keywords=제목에 이 글자가 있으면 이 종류로 봅니다
    {"key": "sunday", "name": "주보",     "dir": "sunday", "env": "SUNDAY_NUMBER",
     "keywords": ["주보", "주일예배", "주일 예배", "주일"]},
    {"key": "friday", "name": "금요집회", "dir": "friday", "env": "FRIDAY_NUMBER",
     "keywords": ["금요집회", "금요 집회", "금요예배", "금요 예배", "금요"]},
]
SKIP_KEYWORD = "주간충현"   # 제목에 이 글자가 있으면 무조건 건너뜁니다 (주간충현은 다른 프로그램이 받습니다)
SEED_BASE = int(os.environ.get("SEED_BASE", "1270"))      # 아직 받아 둔 것이 없을 때, 이 번호 다음부터 찾아봅니다
SEARCH_AHEAD = int(os.environ.get("SEARCH_AHEAD", "12"))  # 지금 번호보다 몇 번 앞까지 찾아볼지 (번호가 건너뛰어도 찾게 하는 여유분)
MIN_PAGES = 1           # 쪽 이미지가 이 장수 이상인 페이지만 순서지로 봅니다
SCAN_TIMEOUT = 20       # 번호 하나를 확인할 때 기다리는 최대 시간(초)
MAX_CONN_FAIL = 3       # 접속이 연달아 이만큼 실패하면 찾기를 멈춥니다 (사이트가 안 열리는 경우)
PAUSE = 0.3             # 번호와 번호 사이 쉬는 시간(초). 웹진 서버에 부담을 주지 않으려는 배려입니다

ROOT = fw.ROOT          # 저장소 맨 위 폴더


def log(msg):
    print(msg, flush=True)


def kind_dir(k):
    return os.path.join(ROOT, k["dir"])


def read_current(k):
    """이미 받아 둔 사본 정보(data.json)를 읽습니다. 없으면 빈 칸."""
    try:
        with open(os.path.join(kind_dir(k), "data.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def classify(title):
    """페이지 제목을 보고 어떤 종류인지 알려 줍니다. 해당 없으면 None."""
    if SKIP_KEYWORD in title:
        return None
    for k in KINDS:
        if any(w in title for w in k["keywords"]):
            return k
    return None


def fetch_page(number):
    """번호 하나를 열어 봅니다. 쪽 이미지가 있으면 (제목, 페이지글, 주소)를, 없으면 None, 접속 실패면 'FAIL' 을 돌려줍니다."""
    url = fw.WEBZINE_BASE.rstrip("/") + "/" + str(number)
    for ua in (fw.HEADERS["User-Agent"], fw.MOBILE_UA):   # 컴퓨터용으로 목록이 없으면 휴대폰용으로 한 번 더
        try:
            r = requests.get(url, headers=dict(fw.HEADERS, **{"User-Agent": ua}), timeout=SCAN_TIMEOUT)
        except requests.RequestException as e:
            log("  [찾기] %s번 접속 실패(%s)" % (number, type(e).__name__))
            return "FAIL"
        if r.status_code != 200:   # 404 등: 없는 번호
            return None
        if len(fw.find_pages(r.text)) >= MIN_PAGES:
            return fw.find_title(r.text, number), r.text, url
    return None


def save_kind(k, number, html, url):
    """쪽 이미지를 받아 sunday/ 또는 friday/ 폴더에 저장하고 data.json 을 씁니다. 전부 성공했을 때만 기존 사본과 바꿉니다."""
    urls = fw.find_pages(html)
    for u in urls:
        if not fw.safe_image_url(u):
            raise RuntimeError("허용되지 않은 이미지 주소입니다: %s" % u)
    log("  %s: 쪽 이미지 %d장 발견" % (k["name"], len(urls)))
    d = kind_dir(k)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "img_new")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    pages = []
    try:
        for i, u in enumerate(urls, 1):
            name = "p%d.jpg" % i
            w, h = fw.download_and_shrink(u, os.path.join(tmp, name))
            log("    %d쪽 저장: %dx%d, %dKB" % (i, w, h, os.path.getsize(os.path.join(tmp, name)) // 1024))
            pages.append({"src": "img/" + name, "w": w, "h": h})
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    img = os.path.join(d, "img")
    shutil.rmtree(img, ignore_errors=True)
    os.replace(tmp, img)
    kst = timezone(timedelta(hours=9))
    data = {
        "number": str(number),
        "title": fw.find_title(html, number),
        "pages": pages,
        "updated": datetime.now(kst).strftime("%Y-%m-%d %H:%M"),
        "source": url,
    }
    with open(os.path.join(d, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log("  완료: %s → %s (%d쪽)" % (k["name"], data["title"], len(pages)))


def have_all(k, cur, number):
    """이미 같은 번호를 받아 두었고 이미지도 다 있는지."""
    return cur.get("number") == str(number) and cur.get("pages") and all(
        os.path.exists(os.path.join(kind_dir(k), p["src"])) for p in cur["pages"])


def main():
    errors = 0
    force = bool(os.environ.get("FORCE", "").strip())
    cur = {k["key"]: read_current(k) for k in KINDS}
    todo = {}   # 종류 key → (번호, 페이지글, 주소) : 이번에 받을 것

    # ── 1) 번호를 직접 지정한 종류: 제목과 상관없이 그 번호를 받습니다 ──
    auto_kinds = []
    for k in KINDS:
        v = os.environ.get(k["env"], "").strip()
        m = re.search(r"(\d+)\s*$", v) if v else None
        if m:
            n = m.group(1)
            log("%s: 번호를 직접 지정받았습니다: %s" % (k["name"], n))
            try:
                url = fw.WEBZINE_BASE.rstrip("/") + "/" + n
                html = fw.http_get(url).text
                if not fw.find_pages(html):
                    raise RuntimeError("이 페이지에서 쪽 이미지 목록을 찾지 못했습니다: %s" % url)
                log("  제목: %s" % fw.find_title(html, n))
                todo[k["key"]] = (int(n), html, url)
            except Exception as e:
                log("오류(%s): %s" % (k["name"], e))
                errors += 1
        else:
            auto_kinds.append(k)

    # ── 2) 나머지는 번호를 쭉 훑어 가며 제목으로 찾습니다 ──
    if auto_kinds:
        base = {}
        for k in auto_kinds:
            c = cur[k["key"]].get("number")
            base[k["key"]] = int(c) if str(c).isdigit() else SEED_BASE
        lo, hi = min(base.values()) + 1, max(base.values()) + SEARCH_AHEAD
        log("새 순서지 찾는 중: %d번 ~ %d번을 확인합니다 (%s)" % (lo, hi, ", ".join(
            "%s 현재 %s" % (k["name"], cur[k["key"]].get("number", "없음")) for k in auto_kinds)))
        fails = 0
        for n in range(lo, hi + 1):
            got = fetch_page(n)
            time.sleep(PAUSE)
            if got == "FAIL":
                fails += 1
                if fails >= MAX_CONN_FAIL:
                    log("접속이 계속 안 되어 찾기를 멈춥니다. 기존 사본은 그대로 둡니다.")
                    break
                continue
            fails = 0
            if not got:
                continue
            title, html, url = got
            k = classify(title)
            if not k:
                log("  [찾기] %d번은 주보·금요집회가 아니어서 건너뜁니다: %s" % (n, title))
                continue
            if k not in auto_kinds or n <= base[k["key"]]:
                continue
            log("  [찾기] %d번 발견 → %s: %s" % (n, k["name"], title))
            todo[k["key"]] = (n, html, url)   # 더 큰 번호가 나오면 덮어써서 가장 새로운 것만 남깁니다

    # ── 3) 찾은 것 받아서 저장 ──
    for k in KINDS:
        got = todo.get(k["key"])
        if not got:
            log("%s: 새 순서지 없음. 현재 %s 을(를) 유지합니다." % (k["name"], cur[k["key"]].get("number", "(아직 없음)")))
            continue
        n, html, url = got
        if have_all(k, cur[k["key"]], n) and not force:
            log("%s: 이미 %d번 사본이 있습니다. 할 일이 없습니다." % (k["name"], n))
            continue
        try:
            save_kind(k, n, html, url)
        except Exception as e:
            log("오류(%s): %s — 기존 사본은 그대로 둡니다." % (k["name"], e))
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("오류: %s" % e)
        sys.exit(1)

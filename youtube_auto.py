"""유튜브 자동 업로드 - 폴더 버전

'업로드할영상' 폴더에 영상을 넣어두면 알아서 유튜브에 올리고
'업로드완료' 폴더로 옮겨줍니다.

실행 예시:
  python youtube_auto.py                      # 폴더에 있는 영상 지금 한 번 다 올리기
  python youtube_auto.py --watch              # 켜두면 10분마다 폴더 확인해서 새 영상 올리기
  python youtube_auto.py --schedule 18:00     # 매일 18시에 하나씩 공개되도록 예약 업로드
"""
import argparse
import json
import os
import shutil
import time
from datetime import datetime, timedelta

import youtube_core as yc

# ─── 기본 설정 (원하면 여기만 바꾸세요) ───
INPUT_DIR = "업로드할영상"
DONE_DIR = "업로드완료"
DEFAULT_PRIVACY = "비공개"        # 비공개 / 일부공개 / 공개
DEFAULT_CATEGORY = "인물/블로그"   # youtube_core.py 의 CATEGORIES 참고
DEFAULT_TAGS = []                # 예: ["경제", "주식"]
DEFAULT_DESCRIPTION = ""
CHECK_EVERY_MINUTES = 10         # --watch 일 때 폴더 확인 간격
SCHEDULE_STATE_FILE = "schedule_state.json"  # 마지막 예약 날짜 기억용


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def read_info(video_path):
    """영상과 같은 이름의 .txt 파일이 있으면 제목/태그/설명을 읽습니다.

    예) 내영상.mp4 옆에 내영상.txt:
        제목: 오늘의 경제 뉴스
        태그: 경제, 뉴스, 주식
        설명:
        여기부터 끝까지 전부 설명으로 들어갑니다.
    """
    base = os.path.splitext(video_path)[0]
    info = {
        "title": os.path.basename(base),
        "tags": list(DEFAULT_TAGS),
        "description": DEFAULT_DESCRIPTION,
        "txt": None,
        "thumbnail": None,
    }
    for ext in (".jpg", ".jpeg", ".png"):
        if os.path.exists(base + ext):
            info["thumbnail"] = base + ext
            break

    txt = base + ".txt"
    if not os.path.exists(txt):
        return info
    info["txt"] = txt
    with open(txt, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("제목:"):
            info["title"] = line[3:].strip() or info["title"]
        elif line.startswith("태그:"):
            info["tags"] = [t.strip() for t in line[3:].split(",") if t.strip()]
        elif line.startswith("설명:"):
            first = line[3:].strip()
            rest = lines[i + 1:]
            info["description"] = "\n".join(([first] if first else []) + rest).strip()
            break
    return info


def next_schedule_time(hhmm):
    """다음 예약 공개 시간: 마지막 예약일 다음 날 (최소 오늘 이후) 같은 시각."""
    hour, minute = map(int, hhmm.split(":"))
    now = datetime.now(yc.KST)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now + timedelta(minutes=30):
        candidate += timedelta(days=1)

    if os.path.exists(SCHEDULE_STATE_FILE):
        with open(SCHEDULE_STATE_FILE, encoding="utf-8") as f:
            last = datetime.fromisoformat(json.load(f)["last"])
        after_last = last.replace(hour=hour, minute=minute) + timedelta(days=1)
        candidate = max(candidate, after_last)
    return candidate


def remember_schedule(dt):
    with open(SCHEDULE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last": dt.isoformat()}, f)


def move_to_done(*paths):
    os.makedirs(DONE_DIR, exist_ok=True)
    for p in paths:
        if p and os.path.exists(p):
            shutil.move(p, os.path.join(DONE_DIR, os.path.basename(p)))


def find_videos():
    os.makedirs(INPUT_DIR, exist_ok=True)
    files = [os.path.join(INPUT_DIR, f) for f in sorted(os.listdir(INPUT_DIR))
             if f.lower().endswith(yc.VIDEO_EXTENSIONS)]
    # 아직 복사 중인 파일은 건너뛰기 (1분 이상 변화 없는 파일만)
    return [f for f in files if time.time() - os.path.getmtime(f) > 60]


def process_folder(youtube, schedule):
    """폴더의 영상을 올립니다. 오늘 한도가 끝났으면 False."""
    videos = find_videos()
    if not videos:
        log(f"'{INPUT_DIR}' 폴더에 올릴 영상이 없습니다.")
        return True

    for path in videos:
        info = read_info(path)
        publish_at = next_schedule_time(schedule) if schedule else None
        log(f"업로드 시작: {os.path.basename(path)} → '{info['title']}'")
        try:
            last_shown = [-10]

            def progress(p):
                if p - last_shown[0] >= 10 or p == 100:
                    log(f"  {p}%")
                    last_shown[0] = p

            video_id = yc.upload_video(
                youtube, path, info["title"], info["description"], info["tags"],
                category_id=yc.CATEGORIES[DEFAULT_CATEGORY],
                privacy=yc.PRIVACY[DEFAULT_PRIVACY],
                publish_at=publish_at,
                thumbnail_path=info["thumbnail"],
                on_progress=progress,
            )
        except Exception as e:
            msg = yc.friendly_error(e)
            log(f"❌ 실패: {msg}")
            if "업로드 가능 횟수" in msg:
                return False
            continue

        if publish_at:
            remember_schedule(publish_at)
            log(f"✅ 완료: https://youtu.be/{video_id}  (공개 예정 {publish_at:%Y-%m-%d %H:%M})")
        else:
            log(f"✅ 완료: https://youtu.be/{video_id}")
        move_to_done(path, info["txt"], info["thumbnail"])
    return True


def main():
    parser = argparse.ArgumentParser(description="폴더에 넣은 영상을 유튜브에 자동 업로드")
    parser.add_argument("--watch", action="store_true", help="계속 켜두고 새 영상이 생기면 업로드")
    parser.add_argument("--schedule", metavar="HH:MM", help="매일 이 시간에 하나씩 공개되도록 예약 (예: 18:00)")
    args = parser.parse_args()

    creds = yc.load_credentials()
    if creds is None:
        log("처음 실행이라 로그인이 필요합니다. 브라우저 창이 열리면 로그인해주세요.")
        creds = yc.login()
    youtube = yc.get_youtube(creds)
    log(f"연결된 채널: {yc.get_channel_name(youtube)}")

    if not args.watch:
        process_folder(youtube, args.schedule)
        return

    log(f"자동 모드 시작 ({CHECK_EVERY_MINUTES}분마다 확인). 끄려면 Ctrl+C")
    while True:
        ok = process_folder(youtube, args.schedule)
        wait = CHECK_EVERY_MINUTES if ok else 60 * 3  # 한도 초과면 3시간 뒤 다시
        time.sleep(wait * 60)


if __name__ == "__main__":
    main()

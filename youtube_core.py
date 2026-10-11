"""유튜브 업로드 공통 기능 (로그인 + 영상 업로드)

youtube_app.py(화면 버전)와 youtube_auto.py(폴더 자동 업로드 버전)가 함께 사용합니다.
"""
import os
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# 영상 업로드 + 썸네일 변경에 필요한 권한
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]

CLIENT_SECRET_FILE = "client_secret.json"  # 구글 클라우드에서 받은 OAuth 파일
TOKEN_FILE = "token.json"                  # 로그인 후 자동 저장되는 파일

VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v")

KST = timezone(timedelta(hours=9))

# 자주 쓰는 유튜브 카테고리 (이름 → ID)
CATEGORIES = {
    "인물/블로그": "22",
    "교육": "27",
    "엔터테인먼트": "24",
    "뉴스/정치": "25",
    "노하우/스타일": "26",
    "과학기술": "28",
    "게임": "20",
    "음악": "10",
    "영화/애니메이션": "1",
    "스포츠": "17",
    "여행/이벤트": "19",
    "코미디": "23",
}

PRIVACY = {"비공개": "private", "일부공개": "unlisted", "공개": "public"}


def load_credentials():
    """저장된 로그인 정보를 불러옵니다. 없거나 만료됐으면 None."""
    if not os.path.exists(TOKEN_FILE):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds)
            return creds
        except Exception:
            return None
    return None


def save_credentials(creds):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def login():
    """브라우저를 열어 구글 계정으로 로그인합니다. (처음 한 번만)"""
    if not os.path.exists(CLIENT_SECRET_FILE):
        raise FileNotFoundError(
            f"'{CLIENT_SECRET_FILE}' 파일이 없습니다. 사용설명서(YOUTUBE_README.md)를 참고해 준비해주세요."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    save_credentials(creds)
    return creds


def get_youtube(creds):
    return build("youtube", "v3", credentials=creds)


def get_channel_name(youtube):
    res = youtube.channels().list(part="snippet", mine=True).execute()
    items = res.get("items", [])
    return items[0]["snippet"]["title"] if items else "(채널 없음)"


def to_publish_at(local_dt: datetime) -> str:
    """한국 시간 → 유튜브가 요구하는 UTC 문자열"""
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=KST)
    return local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_video(youtube, file_path, title, description="", tags=None,
                 category_id="22", privacy="private", publish_at=None,
                 made_for_kids=False, thumbnail_path=None, on_progress=None):
    """영상을 업로드하고 영상 ID를 돌려줍니다.

    publish_at: 예약 공개 시간(datetime, 한국 시간). 지정하면 그때까지 비공개였다가 자동 공개됩니다.
    on_progress: 진행률(0~100)을 받는 함수 (선택)
    """
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids}
    if publish_at:
        # 예약 공개는 반드시 '비공개' 상태로 올려야 합니다.
        status["privacyStatus"] = "private"
        status["publishAt"] = to_publish_at(publish_at)

    body = {
        "snippet": {
            "title": title[:100],  # 유튜브 제목은 최대 100자
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": status,
    }

    media = MediaFileUpload(file_path, chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retries = 0
    while response is None:
        try:
            progress, response = request.next_chunk()
            if progress and on_progress:
                on_progress(int(progress.progress() * 100))
        except HttpError as e:
            # 서버 일시 오류면 몇 번 다시 시도
            if e.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                continue
            raise
    if on_progress:
        on_progress(100)

    video_id = response["id"]

    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(thumbnail_path)
            ).execute()
        except HttpError as e:
            # 썸네일은 채널 '고급 기능' 인증이 필요해서 실패할 수 있음 → 영상 업로드는 성공 처리
            print(f"⚠️ 썸네일 설정 실패 (영상은 업로드됨): {e}")

    return video_id


def friendly_error(e: Exception) -> str:
    """자주 나는 오류를 쉬운 말로 바꿔줍니다."""
    text = str(e)
    if "quotaExceeded" in text or "uploadLimitExceeded" in text:
        return "오늘 업로드 가능 횟수를 다 썼습니다. 내일(한국시간 오후 4~5시 이후) 다시 시도해주세요."
    if "invalid_grant" in text or "unauthorized" in text.lower():
        return "로그인이 만료되었습니다. token.json 파일을 지우고 다시 로그인해주세요."
    if "youtubeSignupRequired" in text:
        return "이 구글 계정에 유튜브 채널이 없습니다. 유튜브에서 채널을 먼저 만들어주세요."
    return text

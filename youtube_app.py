"""유튜브 자동 업로드 - 화면 버전

실행:  streamlit run youtube_app.py
"""
import os
import tempfile
from datetime import datetime, timedelta

import streamlit as st

import youtube_core as yc

st.set_page_config(page_title="유튜브 자동 업로드", page_icon="📺", layout="centered")
st.title("📺 유튜브 자동 업로드")


def save_temp(uploaded_file):
    """업로드한 파일을 임시 폴더에 저장하고 경로를 돌려줍니다."""
    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(uploaded_file.getbuffer())
        return f.name


# ─── 1. 로그인 ───
st.header("1. 유튜브 계정 연결")

if "creds" not in st.session_state:
    st.session_state.creds = yc.load_credentials()

if not os.path.exists(yc.CLIENT_SECRET_FILE):
    st.warning("먼저 구글에서 받은 `client_secret.json` 파일을 올려주세요. (방법: YOUTUBE_README.md 참고)")
    secret = st.file_uploader("client_secret.json 올리기", type=["json"])
    if secret:
        with open(yc.CLIENT_SECRET_FILE, "wb") as f:
            f.write(secret.getbuffer())
        st.success("저장했습니다!")
        st.rerun()
    st.stop()

if st.session_state.creds is None:
    if st.button("🔑 유튜브 계정 연결하기 (브라우저 창이 열립니다)", type="primary"):
        try:
            st.session_state.creds = yc.login()
            st.rerun()
        except Exception as e:
            st.error(f"로그인 실패: {yc.friendly_error(e)}")
    st.stop()

youtube = yc.get_youtube(st.session_state.creds)
try:
    channel = yc.get_channel_name(youtube)
    st.success(f"✅ 연결된 채널: **{channel}**")
except Exception as e:
    st.error(yc.friendly_error(e))
    st.stop()

if st.button("다른 계정으로 바꾸기"):
    if os.path.exists(yc.TOKEN_FILE):
        os.remove(yc.TOKEN_FILE)
    st.session_state.creds = None
    st.rerun()

# ─── 2. 영상 선택 ───
st.header("2. 영상 올리기")
videos = st.file_uploader(
    "영상 파일 선택 (여러 개 가능)",
    type=[ext.lstrip(".") for ext in yc.VIDEO_EXTENSIONS],
    accept_multiple_files=True,
)
thumbnail = st.file_uploader("썸네일 이미지 (선택, 영상이 1개일 때만)", type=["jpg", "jpeg", "png"])

# ─── 3. 영상 정보 ───
st.header("3. 영상 정보")
title = st.text_input("제목 (비워두면 파일 이름 사용)", max_chars=100)
description = st.text_area("설명", height=150)
tags_text = st.text_input("태그 (쉼표로 구분, 예: 경제, 주식, 재테크)")

col1, col2 = st.columns(2)
with col1:
    category = st.selectbox("카테고리", list(yc.CATEGORIES.keys()))
with col2:
    privacy = st.selectbox("공개 범위", list(yc.PRIVACY.keys()))

made_for_kids = st.checkbox("아동용 영상입니다")

# ─── 4. 예약 공개 ───
st.header("4. 예약 공개 (선택)")
use_schedule = st.checkbox("정해진 시간에 자동 공개하기")
start_dt = None
gap_hours = 24
if use_schedule:
    tomorrow = datetime.now(yc.KST) + timedelta(days=1)
    c1, c2 = st.columns(2)
    with c1:
        d = st.date_input("첫 영상 공개 날짜", value=tomorrow.date())
    with c2:
        t = st.time_input("공개 시간 (한국 시간)", value=datetime.strptime("18:00", "%H:%M").time())
    start_dt = datetime.combine(d, t).replace(tzinfo=yc.KST)
    if videos and len(videos) > 1:
        gap_hours = st.number_input("영상끼리 공개 간격 (시간)", min_value=1, value=24,
                                    help="24 = 하루에 한 개씩 공개")
    st.caption("예약 공개 영상은 그 시간까지 '비공개'로 있다가 자동으로 공개됩니다.")

# ─── 5. 업로드 ───
st.divider()
if st.button("🚀 업로드 시작", type="primary", disabled=not videos):
    if use_schedule and start_dt <= datetime.now(yc.KST):
        st.error("예약 시간은 지금보다 뒤여야 합니다.")
        st.stop()

    tags = [x.strip() for x in tags_text.split(",") if x.strip()]
    thumb_path = save_temp(thumbnail) if (thumbnail and len(videos) == 1) else None

    for i, video in enumerate(videos):
        name = os.path.splitext(video.name)[0]
        video_title = title or name
        if title and len(videos) > 1:
            video_title = f"{title} {i + 1}"
        publish_at = start_dt + timedelta(hours=gap_hours * i) if use_schedule else None

        st.write(f"**{i + 1}/{len(videos)}** `{video.name}` → {video_title}")
        bar = st.progress(0, text="준비 중...")
        path = save_temp(video)
        try:
            video_id = yc.upload_video(
                youtube, path, video_title, description, tags,
                category_id=yc.CATEGORIES[category],
                privacy=yc.PRIVACY[privacy],
                publish_at=publish_at,
                made_for_kids=made_for_kids,
                thumbnail_path=thumb_path,
                on_progress=lambda p: bar.progress(p, text=f"업로드 중... {p}%"),
            )
            url = f"https://youtu.be/{video_id}"
            msg = f"✅ 완료! {url}"
            if publish_at:
                msg += f"  (공개 예정: {publish_at:%Y-%m-%d %H:%M})"
            st.success(msg)
        except Exception as e:
            st.error(f"❌ 실패: {yc.friendly_error(e)}")
        finally:
            os.remove(path)

    if thumb_path:
        os.remove(thumb_path)
    st.balloons()

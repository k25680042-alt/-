import streamlit as st
import io
import re
import time
import math
from google import genai
from google.genai import types
from PIL import Image

# ─── 모델 설정 ───
TEXT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "gemini-3.1-flash-image-preview"
CHARS_PER_SECOND = 4.5  # 한국어 내레이션 기준 1초당 ~4.5글자(공백 포함)

# ─── 기본 스타일 가이드 템플릿 ───
DEFAULT_STYLE_TEMPLATE = """💎 Gems 시스템 지침 (System Instructions) - [Simple & Economic Focus Ver 7.0]
당신은 '2D 스틱맨 애니메이션 전문 프롬프트 디렉터'입니다.

#### 🎨 스타일 가이드 (Style Lock)
1. 비주얼 정의 (Visuals)
 캐릭터: Pure-white round faces, single hard cel shading(턱 아래 1단 그림자), thick black outline, thicker torso and neck, stick limbs, flat matte colors.
 배경: 저채도 평면 블록(Low saturation flat blocks), 글자 절대 금지.
 네거티브(내재): 3D, photoreal, gradient, soft light, text, letters, speech bubble.

2. 장면 해석 (Scene Interpretation)
 행동 중심: 감정은 눈썹/입선으로, 동작은 명확한 동사(leans, points, nods, clasps, gestures)로 표현.
 경제 개념 시각화: 추상적 개념은 인물+아이콘/도형으로 변환.
     상승/하락 → 화살표 아이콘(Arrow icons)
     데이터/실적 → 차트 도형, 기어, 지도 핀 (Chart shapes, Gears, Map pins)
     계약/문서 → 빈 종이 아이콘 (Blank paper icons)
     주의: 모든 간판, 화면, 문서에 글자(Text) 대신 기호/도형만 사용.

#### 📝 출력 템플릿 (Output Template)
모든 프롬프트는 반드시 아래 문장으로 시작해야 합니다. 대괄호 `[...]` 부분만 장면에 맞춰 영문으로 작성하세요.

> Upgraded stick-man 2D with thick black outline, pure white faces, single hard cel shading, thicker torso and neck, flat matte colors; SCENE: [행동 및 아이콘 묘사 (영문) + no text/letters 강조]
"""


# ─── 헬퍼 함수 ───

def get_client(api_key: str) -> genai.Client:
    """Gemini API 클라이언트 생성"""
    return genai.Client(api_key=api_key)


def analyze_script(client: genai.Client, script: str) -> str:
    """1단계: 대본 분석 - 주제, 분위기, 핵심 장면, 시각 요소 파악"""
    prompt = f"""다음 한국어 대본을 분석해주세요. 아래 항목별로 정리해주세요:

1. **주제 및 핵심 메시지**: 대본이 전달하려는 핵심 내용
2. **분위기/톤**: 전체적인 분위기 (예: 진지, 유머, 교육적 등)
3. **등장 요소**: 언급되는 인물, 사물, 개념
4. **시각화 포인트**: 이미지로 표현하면 좋을 핵심 장면들
5. **전체 흐름**: 대본의 기승전결 구조

대본:
{script}"""

    response = client.models.generate_content(
        model=TEXT_MODEL,
        contents=prompt,
    )
    return response.text


def segment_script(script: str, seconds_per_cut: int) -> list:
    """2단계: 초단위 분할 - 한국어 내레이션 기준으로 대본을 세그먼트로 나눔"""
    chars_per_cut = int(seconds_per_cut * CHARS_PER_SECOND)

    # 문장 단위로 분리 (마침표, 느낌표, 물음표, 줄바꿈)
    raw_sentences = re.split(r'(?<=[.!?。])\s*|\n+', script.strip())
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    segments = []
    current_text = ""
    idx = 1

    for sentence in sentences:
        # 현재 세그먼트에 추가해도 글자 수 초과하지 않으면 추가
        if current_text and len(current_text + " " + sentence) > chars_per_cut:
            duration = len(current_text) / CHARS_PER_SECOND
            segments.append({
                "index": idx,
                "text": current_text,
                "duration_seconds": round(duration, 1),
            })
            idx += 1
            current_text = sentence
        elif not current_text:
            current_text = sentence
        else:
            current_text = current_text + " " + sentence

    # 마지막 남은 텍스트
    if current_text:
        duration = len(current_text) / CHARS_PER_SECOND
        segments.append({
            "index": idx,
            "text": current_text,
            "duration_seconds": round(duration, 1),
        })

    return segments


def generate_image_prompts(
    client: genai.Client,
    segments: list,
    script_analysis: str,
    style_template: str,
) -> list:
    """3단계: 이미지 프롬프트 생성 - 각 세그먼트별 영문 이미지 프롬프트"""
    segments_text = "\n".join(
        f"{seg['index']}. {seg['text']}" for seg in segments
    )

    prompt = f"""당신은 2D 스틱맨 애니메이션 전문 프롬프트 디렉터입니다.

아래의 [스타일 가이드]와 [대본 분석], [세그먼트 목록]을 참고하여,
각 세그먼트에 대해 **영문 이미지 생성 프롬프트**를 1개씩 작성해주세요.

### 규칙:
- 모든 프롬프트는 반드시 다음 문장으로 시작: "Upgraded stick-man 2D with thick black outline, pure white faces, single hard cel shading, thicker torso and neck, flat matte colors; SCENE: "
- SCENE 이후에 해당 세그먼트의 내용을 시각적으로 묘사 (영문)
- 반드시 "no text or letters" 를 포함
- 캐릭터는 stick-man 스타일, 배경은 low saturation flat blocks
- 추상적 개념은 아이콘/도형으로 시각화 (화살표, 차트, 기어 등)
- 출력 형식: 번호. 프롬프트 (한 줄에 하나씩)

### [스타일 가이드]
{style_template}

### [대본 분석]
{script_analysis}

### [세그먼트 목록]
{segments_text}

위 세그먼트 각각에 대해 번호를 매겨 영문 이미지 프롬프트를 작성해주세요.
출력 형식 (정확히 이 형식을 따르세요):
1. "Upgraded stick-man 2D ... SCENE: ..."
2. "Upgraded stick-man 2D ... SCENE: ..."
..."""

    response = client.models.generate_content(
        model=TEXT_MODEL,
        contents=prompt,
    )

    # 번호 매긴 프롬프트 파싱
    text = response.text
    pattern = r'^\d+\.\s*["\"]?(Upgraded stick-man.+?)["\"]?\s*$'
    matches = re.findall(pattern, text, re.MULTILINE)

    if len(matches) == len(segments):
        return matches

    # 폴백: 줄 단위로 번호 패턴 매칭
    lines = text.strip().split("\n")
    prompts = []
    for line in lines:
        line = line.strip()
        m = re.match(r'^\d+\.\s*["\"]?(.+?)["\"]?\s*$', line)
        if m:
            prompts.append(m.group(1))

    if len(prompts) == len(segments):
        return prompts

    # 최종 폴백: 개별 호출
    prompts = []
    for seg in segments:
        individual_prompt = f"""다음 한국어 텍스트를 위한 영문 이미지 생성 프롬프트를 작성해주세요.

스타일: {style_template}

텍스트: {seg['text']}

반드시 다음 문장으로 시작하세요:
"Upgraded stick-man 2D with thick black outline, pure white faces, single hard cel shading, thicker torso and neck, flat matte colors; SCENE: "

프롬프트만 출력하세요 (따옴표 없이, 한 줄로)."""

        resp = client.models.generate_content(
            model=TEXT_MODEL,
            contents=individual_prompt,
        )
        result = resp.text.strip().strip('"').strip("'")
        prompts.append(result)

    return prompts


def generate_single_image(client: genai.Client, prompt: str) -> Image.Image:
    """4단계: 단일 이미지 생성 (Nano Banana 2)"""
    max_retries = 2
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        return part.as_image()
            raise ValueError("이미지 데이터가 응답에 포함되지 않았습니다.")
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))

    raise last_error


def image_to_bytes(image: Image.Image) -> bytes:
    """PIL Image를 PNG 바이트로 변환"""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


# ─── Streamlit 앱 ───

st.set_page_config(
    page_title="이미지 생성기",
    page_icon="🎨",
    layout="wide",
)

st.title("🎨 이미지 생성기")
st.caption("대본을 입력하면 Nano Banana 2 (Gemini) 모델로 스틱맨 스타일 이미지를 자동 생성합니다.")

# ─── 세션 상태 초기화 ───
if "pipeline_results" not in st.session_state:
    st.session_state.pipeline_results = {
        "analysis": None,
        "segments": None,
        "prompts": None,
        "images": None,
        "status": "idle",
        "current_step": 0,
    }

# ─── 사이드바: 입력 ───
with st.sidebar:
    st.header("설정")

    api_key = st.text_input(
        "🔑 Gemini API Key",
        type="password",
        placeholder="AIza...",
        help="Google AI Studio에서 발급받은 Gemini API 키를 입력하세요.",
    )

    st.divider()

    script = st.text_area(
        "📝 대본 입력",
        height=200,
        placeholder="한국어 대본을 여기에 입력하세요...\n\n예시:\n부자들은 위기를 기회로 삼습니다. 주식 시장이 폭락할 때 오히려 매수 버튼을 누르죠.",
    )

    seconds_per_cut = st.number_input(
        "⏱️ 컷당 초 (Seconds per cut)",
        min_value=1,
        max_value=30,
        value=5,
        help="한 컷당 몇 초 분량으로 대본을 나눌지 설정합니다. (한국어 기준 1초 ≈ 4.5글자)",
    )

    st.divider()

    style_template = st.text_area(
        "🎨 이미지 프롬프트 템플릿",
        value=DEFAULT_STYLE_TEMPLATE,
        height=300,
        help="이미지 프롬프트 생성 시 참고할 스타일 가이드입니다. 수정 가능합니다.",
    )

    st.divider()

    generate_button = st.button(
        "🚀 생성 시작",
        type="primary",
        disabled=(not api_key or not script),
        use_container_width=True,
    )

    if not api_key:
        st.warning("API Key를 입력해주세요.")
    elif not script:
        st.info("대본을 입력해주세요.")

# ─── 메인 영역: 파이프라인 실행 ───

if generate_button:
    results = st.session_state.pipeline_results
    results.update({
        "analysis": None,
        "segments": None,
        "prompts": None,
        "images": None,
        "status": "running",
        "current_step": 0,
    })

    try:
        client = get_client(api_key)
    except Exception as e:
        st.error(f"API 클라이언트 생성 실패: {e}")
        st.stop()

    # ── Step 1: 대본분석 ──
    with st.status("1/4 📖 대본분석 중...", expanded=True) as s1:
        results["current_step"] = 1
        try:
            analysis = analyze_script(client, script)
            results["analysis"] = analysis
            st.markdown(analysis)
            s1.update(label="1/4 📖 대본분석 완료 ✅", state="complete")
        except Exception as e:
            s1.update(label="1/4 📖 대본분석 실패 ❌", state="error")
            st.error(f"대본 분석 중 오류 발생: {e}")
            results["status"] = "error"
            st.stop()

    # ── Step 2: 초단위 분할 ──
    with st.status("2/4 ✂️ 초단위 분할 중...", expanded=True) as s2:
        results["current_step"] = 2
        segments = segment_script(script, seconds_per_cut)
        results["segments"] = segments

        for seg in segments:
            st.markdown(f"**[{seg['index']}]** ({seg['duration_seconds']}초) {seg['text']}")

        s2.update(
            label=f"2/4 ✂️ 분할 완료 - {len(segments)}개 세그먼트 ✅",
            state="complete",
        )

    # ── Step 3: 이미지 프롬프트 생성 ──
    with st.status("3/4 💡 이미지 프롬프트 생성 중...", expanded=True) as s3:
        results["current_step"] = 3
        try:
            prompts = generate_image_prompts(
                client, segments, analysis, style_template
            )
            results["prompts"] = prompts

            for i, p in enumerate(prompts):
                st.code(p, language="css")

            s3.update(label="3/4 💡 프롬프트 생성 완료 ✅", state="complete")
        except Exception as e:
            s3.update(label="3/4 💡 프롬프트 생성 실패 ❌", state="error")
            st.error(f"프롬프트 생성 중 오류 발생: {e}")
            results["status"] = "error"
            st.stop()

    # ── Step 4: 이미지 생성 ──
    with st.status(
        f"4/4 🖼️ 이미지 생성 중... (0/{len(prompts)})", expanded=True
    ) as s4:
        results["current_step"] = 4
        images = []
        progress = st.progress(0.0)

        for i, prompt in enumerate(prompts):
            st.text(f"생성 중: Cut {i + 1}/{len(prompts)}")
            try:
                img = generate_single_image(client, prompt)
                images.append({"image": img, "prompt": prompt, "error": None})
            except Exception as e:
                images.append({"image": None, "prompt": prompt, "error": str(e)})
            progress.progress((i + 1) / len(prompts))
            s4.update(
                label=f"4/4 🖼️ 이미지 생성 중... ({i + 1}/{len(prompts)})"
            )

        results["images"] = images
        success_count = sum(1 for img in images if img["image"] is not None)
        s4.update(
            label=f"4/4 🖼️ 이미지 생성 완료 - {success_count}/{len(images)} 성공 ✅",
            state="complete",
        )

    results["status"] = "complete"
    st.success(f"파이프라인 완료! {success_count}/{len(images)}개 이미지 생성 성공")

# ─── 결과 표시 (세션 상태에서 복원) ───
results = st.session_state.pipeline_results

if results["status"] == "complete" and results["images"]:
    st.divider()
    st.header("📸 생성된 이미지")

    cols_per_row = 3
    image_list = results["images"]

    for row_start in range(0, len(image_list), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            idx = row_start + j
            if idx >= len(image_list):
                break
            item = image_list[idx]
            with col:
                st.subheader(f"Cut {idx + 1}")
                if item["image"] is not None:
                    st.image(item["image"], use_container_width=True)
                    img_bytes = image_to_bytes(item["image"])
                    st.download_button(
                        label=f"⬇️ 다운로드 Cut {idx + 1}",
                        data=img_bytes,
                        file_name=f"cut_{idx + 1}.png",
                        mime="image/png",
                        key=f"dl_{idx}",
                    )
                else:
                    st.error(f"생성 실패: {item['error']}")
                with st.expander("프롬프트 보기"):
                    st.code(item["prompt"], language="css")

    # 전체 프롬프트 목록
    with st.expander("📋 전체 프롬프트 목록"):
        for i, item in enumerate(image_list):
            st.markdown(f"**Cut {i + 1}:**")
            st.code(item["prompt"], language="css")

    # 세그먼트 목록
    if results["segments"]:
        with st.expander("📝 대본 분할 결과"):
            for seg in results["segments"]:
                st.markdown(
                    f"**[{seg['index']}]** ({seg['duration_seconds']}초) {seg['text']}"
                )

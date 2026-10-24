import random
import time
import uuid
from datetime import datetime, timezone

import gspread
import streamlit as st
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="구매 의사결정 실험", page_icon="🧪", layout="centered")

HEADERS = [
    "response_id", "participant_id", "experiment_version", "condition",
    "stimulus_text", "product", "price_krw", "choice_y", "response_time_s",
    "started_at_utc", "answered_at_utc", "saved_at_utc", "timing_method",
]
VERSION = "nudge-demo-v1"
CONDITIONS = {
    "control": "이 텀블러의 판매 가격은 9,900원입니다.",
    "loss_aversion": "지금 구매하지 않으면 이 텀블러를 9,900원에 구매할 혜택을 놓치게 됩니다.",
    "scarcity": "이 텀블러는 9,900원이며, 현재 재고가 3개 남아 있습니다.",
    "social_proof": "이 텀블러는 9,900원이며, 이미 1,200명이 구매했습니다.",
    "anchoring": "이 텀블러의 비교 기준 가격은 19,900원이며, 현재 판매 가격은 9,900원입니다.",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@st.cache_resource
def get_worksheet():
    config = dict(st.secrets["connections"]["gsheets"])
    credentials = {
        key: value for key, value in config.items()
        if key not in {"spreadsheet", "worksheet", "ttl"}
    }
    client = gspread.service_account_from_dict(credentials)
    client.set_timeout(20)
    sheet = client.open_by_url(config["spreadsheet"])
    return sheet.worksheet(config.get("worksheet", "responses"))


@st.cache_data(ttl=60, show_spinner=False)
def validate_headers():
    # streamlit-gsheets 는 표 머리글 확인에 사용합니다. 전체 데이터를 읽어서 덮어쓰지 않습니다.
    config = st.secrets["connections"]["gsheets"]
    conn = st.connection("gsheets", type=GSheetsConnection)
    frame = conn.read(
        spreadsheet=config["spreadsheet"],
        worksheet=config.get("worksheet", "responses"),
        ttl=0,
        nrows=0,
    )
    if list(frame.columns) != HEADERS:
        raise ValueError("Sheet headers do not match HEADERS")
    return True


def save_response(record):
    worksheet = get_worksheet()
    # 재시도 전 response_id를 확인하여 중복 가능성을 줄입니다.
    # DB 고유 제약이 아니므로 엄격한 exactly-once를 보장하지 않습니다.
    if record["response_id"] in worksheet.col_values(1)[1:]:
        return
    payload = dict(record, saved_at_utc=utc_now())
    worksheet.append_row(
        [payload[name] for name in HEADERS],
        value_input_option="RAW",
        insert_data_option="INSERT_ROWS",
        table_range="A:M",
    )


def begin_trial():
    state = st.session_state
    state.condition = random.choice(list(CONDITIONS))
    state.response_id = str(uuid.uuid4())
    state.stage = "trial"
    state.pop("t0", None)
    state.pop("started_at", None)


def choose(choice_y):
    state = st.session_state
    if state.stage != "trial" or "t0" not in state:
        return
    # 콜백 시작 시 측정하여 Google 저장 시간을 제외합니다.
    elapsed = max(0.0, time.perf_counter() - state.t0)
    state.record = {
        "response_id": state.response_id,
        "participant_id": state.participant_id,
        "experiment_version": VERSION,
        "condition": state.condition,
        "stimulus_text": CONDITIONS[state.condition],
        "product": "텀블러",
        "price_krw": 9900,
        "choice_y": int(choice_y),
        "response_time_s": round(elapsed, 4),
        "started_at_utc": state.started_at,
        "answered_at_utc": utc_now(),
        "timing_method": "server_render_to_callback",
    }
    state.stage = "saving"


state = st.session_state
if "stage" not in state:
    state.stage = "intro"
    state.participant_id = str(uuid.uuid4())

st.title("🧪 구매 의사결정 실험")

if state.stage == "intro":
    st.write("가상의 상품 정보를 확인한 뒤 구매 의사를 한 번 선택합니다.")
    st.write("실제 결제는 없으며 이름, 전화번호, 이메일은 수집하지 않습니다.")
    st.info(
        "임의의 세션 번호, 실험 조건, 선택 결과, 근사 반응 시간, 시각을 기록합니다."
        "자료는 본 시연/연구에 사용되며 앱 운영자의 Google 스프레드시트에 저장됩니다."
        "응답 전에는 페이지를 닫아 참여를 중단할 수 있습니다."
    )
    st.caption("실제 연구 전 운영자는 연구 기관, 연락처, 보관 기간, 철회 절차를 추가하세요.")
    consent = st.checkbox("안내를 확인했으며 자발적으로 참여합니다")
    if st.button("실험 시작", type="primary", disabled=not consent):
        try:
            with st.spinner("데이터 연결 확인 중…"):
                validate_headers()
                get_worksheet()
        except Exception as exc:
            st.error("연결을 확인하지 못했습니다. 관리자는 키, 시트 공유 권한, 머리글을 확인하세요.")
            st.caption(f"오류 유형: {type(exc).__name__}; 키 보호를 위해 상세 오류는 표시하지 않습니다.")
        else:
            begin_trial()
            st.rerun()

elif state.stage == "trial":
    st.subheader("텀블러 구매를 고민 중이라고 가정해 주세요")
    st.caption("페이지를 열린 상태로 유지하고 첫 반응에 따라 선택해 주세요.")
    st.info(CONDITIONS[state.condition])
    st.metric("구매 가격", "9,900원")
    if "t0" not in state:
        state.started_at = utc_now()
        state.t0 = time.perf_counter()
    left, right = st.columns(2)
    left.button("구매하겠습니다", type="primary", on_click=choose, args=(1,))
    right.button("구매하지 않겠습니다", on_click=choose, args=(0,))

elif state.stage == "saving":
    try:
        with st.spinner("응답 저장 중입니다. 페이지를 닫거나 새로고침하지 마세요…"):
            save_response(state.record)
    except Exception as exc:
        st.error("저장 여부를 확인하지 못했습니다. 응답은 현재 세션에 임시 보관됩니다. 새로고침하지 마세요.")
        st.caption(f"오류 유형: {type(exc).__name__}")
        st.caption("재시도 시 이번 response_id가 이미 저장되었는지 먼저 확인합니다.")
        if st.button("저장 재시도", type="primary"):
            st.rerun()
    else:
        state.stage = "done"
        st.rerun()

elif state.stage == "done":
    st.success("응답이 저장되었습니다. 참여해 주셔서 감사합니다!")
    st.write("이 실험은 무작위로 배정된 문구에 따른 구매 의사 차이를 살펴봅니다.")
    st.write("재고, 구매 인원, 비교 가격은 가상의 실험 자극이며 실제 광고가 아닙니다.")
    st.caption("세션당 1회만 참여해 주세요. 새로고침이나 기기 변경 시 새 세션이 생성될 수 있습니다.")

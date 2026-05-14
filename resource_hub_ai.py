import os
import time
import json
import base64
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ==========================================
# 0. 頁面設定
# ==========================================
st.set_page_config(
    page_title="韌性臺灣 - 資源調配中樞",
    layout="wide",
    page_icon="⚖️",
    initial_sidebar_state="expanded"
)

# ==========================================
# 0-1. 響應式 CSS：修正 Community Cloud 顯示不完整
# ==========================================
st.markdown("""
<style>
/* 整體內容寬度與間距 */
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 100%;
}

/* 標題在小螢幕不要爆版 */
h1, h2, h3 {
    word-break: break-word;
}

/* dataframe、map、圖片容器避免超出 */
[data-testid="stDataFrame"],
[data-testid="stTable"],
[data-testid="stImage"],
[data-testid="stMap"] {
    width: 100% !important;
    overflow-x: auto !important;
}

/* sidebar 通知卡片 */
.notify-box {
    border-left: 4px solid #999;
    padding: 8px 10px;
    margin-bottom: 10px;
    font-size: 0.85rem;
    background-color: rgba(250, 250, 250, 0.08);
    border-radius: 6px;
    word-break: break-word;
}

/* 通知區做成可捲動，避免 sidebar 過長 */
.notify-scroll {
    max-height: 360px;
    overflow-y: auto;
    padding-right: 4px;
}

/* 手機 / 窄螢幕 */
@media (max-width: 900px) {
    .block-container {
        padding-left: 1rem;
        padding-right: 1rem;
    }

    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }

    .stButton button {
        width: 100%;
    }

    [data-testid="stMetric"] {
        width: 100%;
    }
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. 系統初始化與狀態管理
# ==========================================
def init_session_state():
    now = datetime.now()

    if "demands" not in st.session_state:
        st.session_state.demands = [
            {
                "id": "D001",
                "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"),
                "source": "Threads",
                "location": "花蓮縣壽豐鄉",
                "lat": 23.871,
                "lon": 121.508,
                "category": "重型機具",
                "item": "抽水機",
                "qty": 5,
                "urgency": 5,
                "status": "未處理",
                "matched_provider": "",
                "raw_text": "壽豐中山路這邊急需大型抽水機😭😭"
            },
            {
                "id": "D002",
                "time": (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"),
                "source": "LINE群組",
                "location": "南投縣仁愛鄉",
                "lat": 24.025,
                "lon": 121.128,
                "category": "民生物資",
                "item": "礦泉水",
                "qty": 100,
                "urgency": 4,
                "status": "未處理",
                "matched_provider": "",
                "raw_text": "仁愛鄉翠華村聯外道路中斷，急需礦泉水支援。"
            }
        ]

    if "supplies" not in st.session_state:
        st.session_state.supplies = [
            {
                "id": "S001",
                "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
                "source": "企業信件",
                "provider": "統一企業",
                "location_current": "台南市永康區",
                "lat": 23.026,
                "lon": 120.254,
                "category": "民生物資",
                "item": "礦泉水",
                "qty": 500,
                "status": "可調派",
                "raw_text": "本公司願捐贈500箱礦泉水，存放於永康物流中心。"
            },
            {
                "id": "S002",
                "time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
                "source": "志工表單",
                "provider": "吉普車救援隊",
                "location_current": "花蓮市區",
                "lat": 23.987,
                "lon": 121.601,
                "category": "重型機具",
                "item": "四輪傳動車與抽水機",
                "qty": 3,
                "status": "可調派",
                "raw_text": "花蓮在地車隊備有3台抽水機可支援涉水。"
            }
        ]

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {
                "role": "assistant",
                "content": "您好！我是防救災通報機器人。請告訴我您目前的所在地與遭遇的情況，或能提供的物資。"
            }
        ]

    if "notifications" not in st.session_state:
        st.session_state.notifications = []


def execute_dispatch(demand_id, supply_id, provider_name):
    demand_info = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    supply_info = next((s for s in st.session_state.supplies if s["id"] == supply_id), None)

    if not demand_info or not supply_info:
        return

    transfer_qty = min(int(demand_info.get("qty", 0)), int(supply_info.get("qty", 0)))

    demand_info["qty"] -= transfer_qty

    if demand_info.get("matched_provider"):
        demand_info["matched_provider"] += f", {provider_name}({transfer_qty}件)"
    else:
        demand_info["matched_provider"] = f"{provider_name}({transfer_qty}件)"

    if demand_info["qty"] <= 0:
        demand_info["status"] = "已完成配對"
    else:
        demand_info["status"] = "部分配對 (尚缺)"

    supply_info["qty"] -= transfer_qty

    if supply_info["qty"] <= 0:
        supply_info["status"] = "已指派 (無庫存)"
    else:
        supply_info["status"] = "可調派 (有剩餘)"

    time_str = datetime.now().strftime("%H:%M:%S")
    demand_loc = demand_info.get("location", "前線災區")
    item_name = demand_info.get("item", "救援物資")

    msg_to_demand = f"📲 [發送至 {demand_loc} 通報人] 已指派【{provider_name}】運送 {transfer_qty} 件 {item_name} 前往支援。"
    msg_to_supply = f"📲 [發送至 {provider_name}] 請協助運送 {transfer_qty} 件 {item_name} 至【{demand_loc}】。"

    st.session_state.notifications.insert(
        0,
        {"time": time_str, "msg": msg_to_demand, "type": "demand"}
    )
    st.session_state.notifications.insert(
        0,
        {"time": time_str, "msg": msg_to_supply, "type": "supply"}
    )

    st.session_state.success_msg = f"🎉 成功調撥 {transfer_qty} 件物資！已自動發送雙向通知。"


# ==========================================
# 2. AI 引擎 A：多模態文字與影像轉譯
# ==========================================
def extract_info_with_ai(raw_text=None, image_bytes=None):
    if not GROQ_API_KEY:
        return {"error": "尚未設定 GROQ_API_KEY"}

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        system_prompt = """
你是一個專業的防災資源調度員。
請判斷輸入內容是「需求 Demand」還是「供給 Supply」，並萃取為標準 JSON。
請利用台灣地理知識，為地點推算大約經緯度。
若無法推算，lat 填 23.5，lon 填 121.0。

請嚴格輸出 JSON：
{
  "info_type": "Demand 或 Supply",
  "data": {
    "location": "若是Demand填需求地點，若是Supply留空",
    "provider": "若是Supply填提供者名稱，若是Demand留空",
    "location_current": "若是Supply填物資/人力所在地，若是Demand留空",
    "category": "物資或機具類別",
    "item": "具體物品",
    "qty": 數量,
    "urgency": 緊急度1到5,
    "lat": 緯度,
    "lon": 經度
  }
}
"""

        messages = [{"role": "system", "content": system_prompt}]

        if image_bytes:
            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "請分析這張災情照片並萃取 JSON：" + str(raw_text)
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            })
            model_name = "llama-3.2-11b-vision-preview"
        else:
            messages.append({"role": "user", "content": str(raw_text)})
            model_name = "llama-3.3-70b-versatile"

        res = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.0
        )

        raw_output = res.choices[0].message.content
        start_idx = raw_output.find("{")
        end_idx = raw_output.rfind("}")

        if start_idx != -1 and end_idx != -1:
            return json.loads(raw_output[start_idx:end_idx + 1])

        return {"error": "格式異常", "raw": raw_output}

    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 3. AI 引擎 B：動態語意與地理媒合
# ==========================================
def ai_match_resources(target_demand, available_supplies):
    if not GROQ_API_KEY:
        return [{"error": "尚未設定 GROQ_API_KEY"}]

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        supplies_str = json.dumps(available_supplies, ensure_ascii=False, indent=2)
        demand_str = json.dumps(target_demand, ensure_ascii=False, indent=2)

        prompt = f"""
你是一個防災資源調度 AI 系統。

前線需求：
{demand_str}

可調派供給：
{supplies_str}

請依據：
1. 地理空間距離
2. 語意吻合
3. 數量充足程度
進行評估。

請只輸出 JSON 陣列：
[
  {{
    "supply_id": "S001",
    "match_score": 90,
    "reason": "理由"
  }}
]
"""

        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )

        raw_output = res.choices[0].message.content
        start_idx = raw_output.find("[")
        end_idx = raw_output.rfind("]")

        if start_idx != -1 and end_idx != -1:
            parsed_data = json.loads(raw_output[start_idx:end_idx + 1])
            return parsed_data if isinstance(parsed_data, list) else [parsed_data]

        return [{"error": "解析失敗", "raw": raw_output}]

    except Exception as e:
        return [{"error": str(e)}]


# ==========================================
# 4. 小工具
# ==========================================
def safe_dataframe(df, columns):
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def add_record_from_ai(result, source, raw_text):
    extracted = result.get("data", result)
    info_type = result.get("info_type", extracted.get("info_type", ""))
    is_demand = "demand" in str(info_type).lower()

    new_record = {
        "id": f"{'D' if is_demand else 'S'}{int(time.time()) % 10000:04d}",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "raw_text": raw_text,
        "status": "未處理" if is_demand else "可調派"
    }

    if is_demand:
        new_record["matched_provider"] = ""

    new_record.update(extracted)

    if not is_demand and "location" in new_record and "location_current" not in new_record:
        new_record["location_current"] = new_record["location"]

    if is_demand:
        st.session_state.demands.append(new_record)
    else:
        st.session_state.supplies.append(new_record)

    return new_record, is_demand


# ==========================================
# 5. 主程式
# ==========================================
init_session_state()

with st.sidebar:
    st.title("⚖️ 韌性臺灣")

    page = st.radio(
        "導覽選單",
        [
            "🏠 首頁介紹",
            "📥 多模態轉譯",
            "💬 前線對話通報",
            "📊 戰備資源池",
            "🤖 AI 調配引擎"
        ]
    )

    st.divider()
    st.subheader("🔔 雙向通知監控台")

    if not st.session_state.notifications:
        st.caption("目前無最新通知。")
    else:
        st.markdown('<div class="notify-scroll">', unsafe_allow_html=True)

        for notif in st.session_state.notifications[:8]:
            color = "#3b82f6" if notif["type"] == "supply" else "#ef4444"
            st.markdown(
                f"""
                <div class="notify-box" style="border-left-color:{color};">
                    <b>{notif["time"]}</b><br>
                    {notif["msg"]}
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown("</div>", unsafe_allow_html=True)

        if len(st.session_state.notifications) > 8:
            st.caption(f"...還有 {len(st.session_state.notifications) - 8} 則歷史通知")


# ==========================================
# 頁面 1：首頁介紹
# ==========================================
if page == "🏠 首頁介紹":
    st.title("🏠 韌性臺灣 - 智慧資源轉譯與調配中樞")

    st.image(
        "https://images.unsplash.com/photo-1518770660439-4636190af475?q=80&w=2070&auto=format&fit=crop",
        use_container_width=True
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric("前線需求", len(st.session_state.demands))
    with c2:
        st.metric("後勤供給", len(st.session_state.supplies))
    with c3:
        pending = len([d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"]])
        st.metric("待處理案件", pending)

    st.markdown("""
### 🎯 解決痛點：打破資訊孤島

在重大災害發生時，民間善心物資與官方救災資源，常因為資訊不對稱、通報管道破碎，而發生資源錯置。

### 🧩 我們的解法：災防微服務積木元件

本系統具備三個核心功能：

1. **視覺與語意轉譯器**：支援圖片與文字，自動萃取成結構化資料。
2. **空間戰情室**：將需求與供給轉換為地圖與表格。
3. **AI 調派引擎**：依地理位置、物資吻合度、數量進行媒合。
""")


# ==========================================
# 頁面 2：多模態轉譯
# ==========================================
elif page == "📥 多模態轉譯":
    st.title("📥 異質情資與影像轉譯")

    col_in, col_out = st.columns([1, 1])

    with col_in:
        uploaded_file = st.file_uploader(
            "📸 上傳災情照片，可選",
            type=["jpg", "png", "jpeg"]
        )

        raw_text_input = st.text_area(
            "補充文字說明",
            placeholder="例如：花蓮壽豐中山路需要抽水機 5 台",
            height=150
        )

        parse_btn = st.button(
            "🧠 啟動多模態解析",
            type="primary",
            use_container_width=True
        )

    with col_out:
        st.subheader("解析結果")

        if parse_btn:
            with st.spinner("AI 解析中..."):
                img_bytes = uploaded_file.getvalue() if uploaded_file else None
                text_to_send = raw_text_input if raw_text_input else "請根據圖片判斷災情與需求。"

                result = extract_info_with_ai(
                    raw_text=text_to_send,
                    image_bytes=img_bytes
                )

                if "error" in result:
                    st.error("解析錯誤")
                    st.code(result.get("error", "unknown error"))
                else:
                    new_record, is_demand = add_record_from_ai(
                        result=result,
                        source="圖片轉譯",
                        raw_text=text_to_send
                    )

                    if is_demand:
                        st.success("✅ 已寫入需求庫")
                    else:
                        st.success("✅ 已寫入供給庫")

                    st.json(result)
        else:
            st.info("請在左側輸入文字或上傳圖片後開始解析。")


# ==========================================
# 頁面 3：Chatbot
# ==========================================
elif page == "💬 前線對話通報":
    st.title("💬 前線防救災 AI 對話助理")

    chat_box = st.container()

    with chat_box:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    user_input = st.chat_input("請輸入您的通報內容...")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("AI 處理中..."):
                result = extract_info_with_ai(raw_text=user_input)

                if "error" not in result:
                    new_record, is_demand = add_record_from_ai(
                        result=result,
                        source="對話通報",
                        raw_text=user_input
                    )

                    place = new_record.get(
                        "location",
                        new_record.get("location_current", "未知")
                    )

                    reply = f"""
✅ 收到！已為您立案。

- **類型**：{"需求" if is_demand else "供給"}
- **地點**：{place}
- **物資**：{new_record.get("item", "未知")} x {new_record.get("qty", 1)}
"""
                else:
                    reply = "抱歉，解析遇到問題，請重新描述地點、物資與數量。"

                st.markdown(reply)
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": reply}
                )


# ==========================================
# 頁面 4：戰備資源池
# ==========================================
elif page == "📊 戰備資源池":
    st.title("📊 空間戰備資源池")

    map_data = []

    for d in st.session_state.demands:
        if d.get("lat") and d.get("lon"):
            map_data.append({
                "lat": float(d["lat"]),
                "lon": float(d["lon"]),
                "color": "#FF0000"
            })

    for s in st.session_state.supplies:
        if s.get("lat") and s.get("lon") and int(s.get("qty", 0)) > 0:
            map_data.append({
                "lat": float(s["lat"]),
                "lon": float(s["lon"]),
                "color": "#00AA00"
            })

    if map_data:
        st.markdown("🔴 **紅色：前線需求** ｜ 🟢 **綠色：後勤供給**")
        st.map(
            pd.DataFrame(map_data),
            color="color",
            zoom=6,
            use_container_width=True
        )
    else:
        st.info("目前尚無可顯示的經緯度資料。")

    st.divider()

    df_d = pd.DataFrame(st.session_state.demands)
    df_s = pd.DataFrame(st.session_state.supplies)

    tab1, tab2 = st.tabs(["🚨 前線需求", "📦 後勤供給"])

    with tab1:
        demand_cols = ["id", "location", "item", "qty", "matched_provider", "status"]
        st.dataframe(
            safe_dataframe(df_d, demand_cols),
            hide_index=True,
            use_container_width=True,
            height=360
        )

    with tab2:
        supply_cols = ["id", "provider", "location_current", "item", "qty", "status"]
        st.dataframe(
            safe_dataframe(df_s, supply_cols),
            hide_index=True,
            use_container_width=True,
            height=360
        )


# ==========================================
# 頁面 5：AI 調配引擎
# ==========================================
elif page == "🤖 AI 調配引擎":
    st.title("🤖 動態 AI 地理與語意媒合")

    if "success_msg" in st.session_state:
        st.success(st.session_state.success_msg)
        del st.session_state.success_msg

    pending_demands = [
        d for d in st.session_state.demands
        if d.get("status") in ["未處理", "部分配對 (尚缺)"]
    ]

    available_supplies = [
        s for s in st.session_state.supplies
        if int(s.get("qty", 0)) > 0
    ]

    if pending_demands and available_supplies:
        col_left, col_right = st.columns([1, 1.4])

        with col_left:
            demand_options = {
                d["id"]: f"[{d['id']}] {d.get('location', '未知地點')} - 缺 {d.get('item', '未知物資')} x {d.get('qty', 0)}"
                for d in pending_demands
            }

            selected_demand_id = st.selectbox(
                "🎯 選擇緊急需求",
                options=list(demand_options.keys()),
                format_func=lambda x: demand_options[x]
            )

            target_demand = next(
                d for d in pending_demands
                if d["id"] == selected_demand_id
            )

            st.info(
                f"""
**需求地點**：{target_demand.get("location", "未知")}  
**需求物資**：{target_demand.get("item", "未知")}  
**尚缺數量**：{target_demand.get("qty", 0)}
"""
            )

            match_btn = st.button(
                "⚡ 啟動 Llama-3 空間媒合",
                type="primary",
                use_container_width=True
            )

        with col_right:
            st.subheader("媒合推薦結果")

            if match_btn:
                with st.spinner("AI 地理空間與數量演算中..."):
                    match_results = ai_match_resources(
                        target_demand,
                        available_supplies
                    )

                    if (
                        not match_results
                        or (
                            isinstance(match_results, list)
                            and len(match_results) > 0
                            and "error" in match_results[0]
                        )
                    ):
                        st.warning("⚠️ 演算失敗或目前無適合資源。")
                        if match_results:
                            st.code(str(match_results[0]))
                    else:
                        for match in match_results:
                            supply_id = match.get("supply_id")
                            supply_info = next(
                                (s for s in available_supplies if s["id"] == supply_id),
                                None
                            )

                            if supply_info:
                                with st.container(border=True):
                                    st.markdown(
                                        f"#### 推薦來源：{supply_info.get('provider', '未知提供者')}"
                                    )

                                    score = int(match.get("match_score", 0))
                                    st.progress(
                                        min(score, 100) / 100,
                                        text=f"契合度：{score} 分"
                                    )

                                    expected_qty = min(
                                        int(target_demand.get("qty", 0)),
                                        int(supply_info.get("qty", 0))
                                    )

                                    st.markdown(
                                        f"""
**供給物資**：{supply_info.get("item", "未知")}  
**目前位置**：{supply_info.get("location_current", "未知")}  
**可用數量**：{supply_info.get("qty", 0)}  
**預計調撥數量**：{expected_qty} 件
"""
                                    )

                                    st.info(f"💡 AI 理由：{match.get('reason', '無')}")

                                    st.button(
                                        "✅ 批准調度",
                                        key=f"btn_{supply_id}_{target_demand['id']}",
                                        on_click=execute_dispatch,
                                        args=(
                                            target_demand["id"],
                                            supply_id,
                                            supply_info.get("provider", "未知提供者")
                                        ),
                                        use_container_width=True
                                    )
            else:
                st.caption("請先選擇需求並啟動媒合。")

    else:
        st.info("目前沒有待處理的任務，或後勤資源已經耗盡。")

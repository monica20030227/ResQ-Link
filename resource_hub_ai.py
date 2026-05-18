import os
import time
import json
import base64
import smtplib
import pandas as pd
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Email 設定：若沒有設定，系統會改用「模擬寄信紀錄」
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

# ==========================================
# 0. 常數設定：資源分類 / 角色 / 認證狀態
# ==========================================
RESOURCE_TAXONOMY = {
    "有形資源": ["食物", "飲用水", "醫療用品", "生活用品", "家具", "救災工具", "交通工具", "重型機具", "通訊設備", "臨時住所"],
    "無形資源": ["人力", "志工", "專業技術", "醫療支援", "心理諮詢", "運輸協助", "資訊彙整", "翻譯協助"],
    "金流資源": ["現金捐款", "物資採購金", "專案補助", "企業贊助"]
}

ROLE_OPTIONS = ["一般民眾", "政府單位", "企業/NGO/志工團體"]
VERIFICATION_OPTIONS = ["✅ 已認證", "🟡 待認證", "⚪ 未認證"]

GOV_DOMAIN_HINTS = ["gov.tw", "mail.gov.tw", "nfa.gov.tw", "moea.gov.tw", "mohw.gov.tw", "ems.gov.tw"]

# ==========================================
# 1. 系統初始化與狀態管理
# ==========================================
def init_session_state():
    now = datetime.now()

    if "users" not in st.session_state:
        st.session_state.users = [
            {
                "user_id": "U001",
                "name": "花蓮壽豐鄉公所",
                "role": "政府單位",
                "email": "shoufeng@gov.tw",
                "phone": "03-0000000",
                "area": "花蓮縣壽豐鄉",
                "org": "花蓮壽豐鄉公所",
                "title": "承辦人",
                "verification_status": "✅ 已認證",
                "blue_check": True,
                "signup_time": now.strftime("%Y-%m-%d %H:%M")
            },
            {
                "user_id": "U002",
                "name": "統一企業",
                "role": "企業/NGO/志工團體",
                "email": "csr@example.com",
                "phone": "06-0000000",
                "area": "台南市永康區",
                "org": "統一企業",
                "title": "CSR窗口",
                "verification_status": "🟡 待認證",
                "blue_check": False,
                "signup_time": now.strftime("%Y-%m-%d %H:%M")
            }
        ]

    if "current_user" not in st.session_state:
        st.session_state.current_user = st.session_state.users[0]

    if "demands" not in st.session_state:
        st.session_state.demands = [
            {
                "id": "D001",
                "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"),
                "source": "Threads",
                "requester": "壽豐村辦公室",
                "requester_email": "shoufeng@gov.tw",
                "location": "花蓮縣壽豐鄉",
                "lat": 23.871,
                "lon": 121.508,
                "resource_type": "有形資源",
                "category": "重型機具",
                "item": "抽水機",
                "qty": 5,
                "urgency": 5,
                "verification_status": "✅ 已認證",
                "verified_by": "花蓮壽豐鄉公所",
                "blue_check": True,
                "status": "未處理",
                "matched_provider": "",
                "raw_text": "壽豐中山路這邊急需大型抽水機😭😭"
            },
            {
                "id": "D002",
                "time": (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"),
                "source": "LINE群組",
                "requester": "翠華村居民",
                "requester_email": "resident@example.com",
                "location": "南投縣仁愛鄉",
                "lat": 24.025,
                "lon": 121.128,
                "resource_type": "有形資源",
                "category": "飲用水",
                "item": "礦泉水",
                "qty": 100,
                "urgency": 4,
                "verification_status": "🟡 待認證",
                "verified_by": "已通知南投縣仁愛鄉公所",
                "blue_check": False,
                "status": "未處理",
                "matched_provider": "",
                "raw_text": "仁愛鄉翠華村聯外道路中斷，急需礦泉水支援。"
            },
            {
                "id": "D003",
                "time": (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"),
                "source": "民眾通報",
                "requester": "受災戶代表",
                "requester_email": "family@example.com",
                "location": "台東縣太麻里鄉",
                "lat": 22.609,
                "lon": 121.005,
                "resource_type": "金流資源",
                "category": "物資採購金",
                "item": "臨時安置採購金",
                "qty": 30000,
                "urgency": 3,
                "verification_status": "⚪ 未認證",
                "verified_by": "尚未認證",
                "blue_check": False,
                "status": "未處理",
                "matched_provider": "",
                "raw_text": "家裡淹水需要臨時採購生活用品與安置費用。"
            }
        ]

    if "supplies" not in st.session_state:
        st.session_state.supplies = [
            {
                "id": "S001",
                "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
                "source": "企業信件",
                "provider": "統一企業",
                "provider_email": "csr@example.com",
                "location_current": "台南市永康區",
                "lat": 23.026,
                "lon": 120.254,
                "resource_type": "有形資源",
                "category": "飲用水",
                "item": "礦泉水",
                "qty": 500,
                "verification_status": "🟡 待認證",
                "blue_check": False,
                "status": "可調派",
                "raw_text": "本公司願捐贈500箱礦泉水，存放於永康物流中心。"
            },
            {
                "id": "S002",
                "time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
                "source": "志工表單",
                "provider": "吉普車救援隊",
                "provider_email": "jeep@example.com",
                "location_current": "花蓮市區",
                "lat": 23.987,
                "lon": 121.601,
                "resource_type": "有形資源",
                "category": "重型機具",
                "item": "四輪傳動車與抽水機",
                "qty": 3,
                "verification_status": "⚪ 未認證",
                "blue_check": False,
                "status": "可調派",
                "raw_text": "花蓮在地車隊備有3台抽水機可支援涉水。"
            },
            {
                "id": "S003",
                "time": (now - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M"),
                "source": "政府備援庫存",
                "provider": "花蓮縣政府消防局",
                "provider_email": "fire@gov.tw",
                "location_current": "花蓮市",
                "lat": 23.991,
                "lon": 121.620,
                "resource_type": "無形資源",
                "category": "人力",
                "item": "救災人力",
                "qty": 20,
                "verification_status": "✅ 已認證",
                "blue_check": True,
                "status": "可調派",
                "raw_text": "可支援20名消防救災人力。"
            }
        ]

    if "claims" not in st.session_state:
        st.session_state.claims = []

    if "notifications" not in st.session_state:
        st.session_state.notifications = []

    if "email_logs" not in st.session_state:
        st.session_state.email_logs = []

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "assistant", "content": "您好！我是防救災通報機器人。請告訴我所在地與需求，或說明您可提供的物資/人力/捐款。"}
        ]


def get_badge(record):
    if record.get("blue_check") or record.get("verification_status") == "✅ 已認證":
        return "✅ 藍勾勾已認證"
    return record.get("verification_status", "⚪ 未認證")


def guess_resource_type(category):
    for resource_type, categories in RESOURCE_TAXONOMY.items():
        if category in categories:
            return resource_type
    return "有形資源"


def normalize_record(record, is_demand=True):
    category = record.get("category", "生活用品")
    record.setdefault("resource_type", guess_resource_type(category))
    record.setdefault("category", category)
    record.setdefault("qty", 1)
    record.setdefault("urgency", 3)
    record.setdefault("verification_status", "⚪ 未認證")
    record.setdefault("blue_check", False)
    record.setdefault("verified_by", "尚未認證")
    if is_demand:
        record.setdefault("requester", st.session_state.current_user.get("name", "一般民眾"))
        record.setdefault("requester_email", st.session_state.current_user.get("email", ""))
        record.setdefault("matched_provider", "")
    else:
        record.setdefault("provider", st.session_state.current_user.get("name", "供給方"))
        record.setdefault("provider_email", st.session_state.current_user.get("email", ""))
        if "location" in record and "location_current" not in record:
            record["location_current"] = record["location"]
    return record


def add_notification(msg, notif_type="system"):
    st.session_state.notifications.insert(0, {
        "time": datetime.now().strftime("%H:%M:%S"),
        "msg": msg,
        "type": notif_type
    })


def send_email(to_email, subject, body):
    """若有 SMTP 環境變數就真的寄信，否則留下模擬寄信紀錄，方便 Demo。"""
    if not to_email:
        st.session_state.email_logs.insert(0, {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "to": "未提供 Email",
            "subject": subject,
            "body": body,
            "status": "略過：未提供收件者"
        })
        return False

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM:
        try:
            msg = MIMEMultipart()
            msg["From"] = SMTP_FROM
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

            status = "已寄出"
            ok = True
        except Exception as e:
            status = f"寄送失敗：{e}"
            ok = False
    else:
        status = "Demo 模式：未設定 SMTP，已建立模擬寄信紀錄"
        ok = True

    st.session_state.email_logs.insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "to": to_email,
        "subject": subject,
        "body": body,
        "status": status
    })
    return ok


def send_match_emails(demand_info, provider_name, provider_email, transfer_qty, mode="AI調度"):
    item_name = demand_info.get("item", "救災物資")
    demand_loc = demand_info.get("location", "前線災區")
    requester_email = demand_info.get("requester_email", "")
    verification = demand_info.get("verification_status", "⚪ 未認證")

    demand_subject = f"【韌性臺灣】您的需求已完成{mode}媒合"
    demand_body = f"""您好，您的救災需求已成功媒合。

需求地點：{demand_loc}
需求項目：{item_name}
媒合供給方：{provider_name}
支援數量：{transfer_qty}
需求認證狀態：{verification}
目前狀態：{demand_info.get('status')}

請保持聯絡方式暢通，等待供給方後續聯繫。
"""

    supply_subject = f"【韌性臺灣】您已成功媒合一筆救災需求"
    supply_body = f"""您好，您已成功媒合/認領一筆救災需求。

需求地點：{demand_loc}
需求項目：{item_name}
支援數量：{transfer_qty}
需求方：{demand_info.get('requester', '未提供')}
需求方 Email：{requester_email or '未提供'}
需求認證狀態：{verification}

請依照平台資訊與需求方聯繫，並保留運送/捐贈紀錄。
"""
    send_email(requester_email, demand_subject, demand_body)
    send_email(provider_email, supply_subject, supply_body)


# ==========================================
# 2. 調度 / 認領 / 認證邏輯
# ==========================================
def execute_dispatch(demand_id, supply_id, provider_name):
    demand_info = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    supply_info = next((s for s in st.session_state.supplies if s["id"] == supply_id), None)

    if not demand_info or not supply_info:
        return

    transfer_qty = min(int(demand_info.get("qty", 0)), int(supply_info.get("qty", 0)))
    if transfer_qty <= 0:
        st.session_state.success_msg = "⚠️ 無可調撥數量。"
        return

    demand_info["qty"] -= transfer_qty
    if demand_info.get("matched_provider"):
        demand_info["matched_provider"] += f", {provider_name}({transfer_qty}件)"
    else:
        demand_info["matched_provider"] = f"{provider_name}({transfer_qty}件)"

    demand_info["status"] = "已完成配對" if demand_info["qty"] <= 0 else "部分配對 (尚缺)"

    supply_info["qty"] -= transfer_qty
    supply_info["status"] = "已指派 (無庫存)" if supply_info["qty"] <= 0 else "可調派 (有剩餘)"

    send_match_emails(
        demand_info=demand_info,
        provider_name=provider_name,
        provider_email=supply_info.get("provider_email", ""),
        transfer_qty=transfer_qty,
        mode="AI調度"
    )

    demand_loc = demand_info.get("location", "前線災區")
    item_name = demand_info.get("item", "救援物資")
    add_notification(f"📲 **[發送至 {demand_loc} 通報人]**\n已指派【{provider_name}】運送 {transfer_qty} 件 {item_name} 前往支援。", "demand")
    add_notification(f"📲 **[發送至 {provider_name}]**\n調度指令下達！請運送 {transfer_qty} 件 {item_name} 至【{demand_loc}】。", "supply")

    st.session_state.success_msg = f"🎉 成功調撥 {transfer_qty} 件資源！已建立 Email 通知紀錄。"


def claim_demand(demand_id, provider_name, provider_email, claim_qty, note):
    demand_info = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    if not demand_info:
        return

    claim_qty = min(int(claim_qty), int(demand_info.get("qty", 0)))
    if claim_qty <= 0:
        st.warning("認領數量需大於 0。")
        return

    demand_info["qty"] -= claim_qty
    demand_info["status"] = "已完成配對" if demand_info["qty"] <= 0 else "部分配對 (尚缺)"
    if demand_info.get("matched_provider"):
        demand_info["matched_provider"] += f", {provider_name}認領({claim_qty}件)"
    else:
        demand_info["matched_provider"] = f"{provider_name}認領({claim_qty}件)"

    claim = {
        "claim_id": f"C{int(time.time()) % 100000:05d}",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "demand_id": demand_id,
        "provider": provider_name,
        "provider_email": provider_email,
        "item": demand_info.get("item", ""),
        "claim_qty": claim_qty,
        "demand_location": demand_info.get("location", ""),
        "demand_verification": demand_info.get("verification_status", ""),
        "note": note,
        "status": "已認領，待雙方聯繫"
    }
    st.session_state.claims.insert(0, claim)

    send_match_emails(
        demand_info=demand_info,
        provider_name=provider_name,
        provider_email=provider_email,
        transfer_qty=claim_qty,
        mode="自主認領"
    )
    add_notification(f"🤝 **自主認領成功**：{provider_name} 認領 {claim_qty} 件 {demand_info.get('item')}，需求地點：{demand_info.get('location')}。", "claim")
    st.success("✅ 認領成功！已建立雙方 Email 通知紀錄。")


def verify_demand(demand_id, verifier_name):
    demand = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    if demand:
        demand["verification_status"] = "✅ 已認證"
        demand["verified_by"] = verifier_name
        demand["blue_check"] = True
        add_notification(f"✅ 需求 {demand_id} 已由 {verifier_name} 認證。", "verify")


def reject_or_mark_unverified(demand_id, verifier_name):
    demand = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    if demand:
        demand["verification_status"] = "⚪ 未認證"
        demand["verified_by"] = f"{verifier_name} 標記未認證"
        demand["blue_check"] = False
        add_notification(f"⚪ 需求 {demand_id} 已被標記為未認證。", "verify")


# ==========================================
# 3. AI 引擎 A：多模態文字與影像轉譯
# ==========================================
def extract_info_with_ai(raw_text=None, image_bytes=None, mime_type="image/jpeg"):
    if not GROQ_API_KEY:
        return {"error": "尚未設定 GROQ_API_KEY"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        taxonomy_text = json.dumps(RESOURCE_TAXONOMY, ensure_ascii=False)
        system_prompt = f"""
        你是一個專業防災資源調度員。請判斷輸入是 Demand 或 Supply，並萃取成 JSON。
        資源必須依照以下分類：{taxonomy_text}
        請輸出格式：
        {{
          "info_type": "Demand 或 Supply",
          "data": {{
              "location": "若是Demand填需求地點，Supply可留空",
              "provider": "若是Supply填提供者，Demand留空",
              "location_current": "若是Supply填所在地，Demand留空",
              "resource_type": "有形資源/無形資源/金流資源",
              "category": "分類細項",
              "item": "具體物品/服務/金額用途",
              "qty": 數量數字,
              "urgency": 緊急度1-5,
              "lat": 緯度浮點數,
              "lon": 經度浮點數
          }}
        }}
        只輸出 JSON，不要額外說明。
        """
        messages = [{"role": "system", "content": system_prompt}]
        if image_bytes:
            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": str(raw_text)},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]
            })
            model_name = "meta-llama/llama-4-scout-17b-16e-instruct"
        else:
            messages.append({"role": "user", "content": str(raw_text)})
            model_name = "llama-3.3-70b-versatile"

        res = client.chat.completions.create(model=model_name, messages=messages, temperature=0.0)
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find("{")
        end_idx = raw_output.rfind("}")
        if start_idx != -1 and end_idx != -1:
            return json.loads(raw_output[start_idx:end_idx + 1])
        return {"error": "格式異常", "raw": raw_output}
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 4. AI 引擎 B：動態語意與地理媒合
# ==========================================
def ai_match_resources(target_demand, available_supplies, trusted_only=False):
    if not GROQ_API_KEY:
        return [{"error": "尚未設定 GROQ_API_KEY"}]
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

        if trusted_only:
            available_supplies = [s for s in available_supplies if s.get("verification_status") == "✅ 已認證"]

        supplies_str = json.dumps(available_supplies, ensure_ascii=False, indent=2)
        demand_str = json.dumps(target_demand, ensure_ascii=False, indent=2)

        prompt = f"""
        你是一個防災資源調度 AI 系統。
        前線需求：\n{demand_str}\n\n可調派供給：\n{supplies_str}
        請依據：
        1. 地理空間距離，優先考慮距離近者
        2. 資源型態 resource_type 是否一致
        3. category 與 item 語意是否吻合
        4. 數量是否足夠
        5. 需求與供給的認證狀態，已認證者信任度更高
        請輸出 JSON 陣列 [...]
        每筆包含：supply_id, match_score, reason。
        只輸出 JSON 陣列，不要額外說明。
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
# 5. Streamlit 介面與導覽路由
# ==========================================
st.set_page_config(page_title="ResQ-Link 韌性臺灣", layout="wide", page_icon="⚖️")
init_session_state()

with st.sidebar:
    st.title("⚖️ ResQ-Link")
    user = st.session_state.current_user
    st.caption("目前登入身分")
    st.markdown(f"**{user.get('name')}**  {('✅' if user.get('blue_check') else '')}")
    st.caption(f"{user.get('role')}｜{user.get('verification_status')}")

    page = st.radio(
        "導覽選單",
        [
            "🏠 首頁介紹",
            "👤 註冊 / 登入",
            "📥 多模態轉譯",
            "💬 前線對話通報",
            "📊 戰備資源池",
            "📋 公開需求認領牆",
            "🤖 AI 調配引擎",
            "✅ 認證審核中心",
            "📧 Email 通知紀錄"
        ]
    )

    st.divider()
    st.subheader("🔔 通知監控台")
    if not st.session_state.notifications:
        st.caption("目前無最新通知。")
    else:
        for notif in st.session_state.notifications[:5]:
            color = "#2b6cb0" if notif["type"] == "supply" else "#c53030" if notif["type"] == "demand" else "#2f855a"
            st.markdown(
                f"<div style='border-left:4px solid {color}; padding-left:10px; margin-bottom:10px; font-size:0.85em;'>"
                f"<b>{notif['time']}</b><br>{notif['msg']}</div>",
                unsafe_allow_html=True
            )

# --- 頁面 1：首頁介紹 ---
if page == "🏠 首頁介紹":
    st.title("🏠 ResQ-Link：可信任防災資源分類、認證與認領平台")
    st.markdown("""
    ### 🎯 核心定位
    本系統從單純的災情資訊蒐集，升級為 **AI 智慧防災資源分配平台**，整合：

    1. **資源分類**：有形資源、無形資源、金流資源。
    2. **藍勾勾認證**：政府單位/里長/公所可認證需求，提高可信度。
    3. **自主認領**：民眾、企業、NGO 可主動認領需求。
    4. **AI 自動媒合**：依地理距離、語意相似、數量與認證狀態推薦調度。
    5. **Email 通知**：配對或認領成功後自動通知需求方與供給方。
    """)

    c1, c2, c3 = st.columns(3)
    c1.metric("待處理需求", len([d for d in st.session_state.demands if d["status"] in ["未處理", "部分配對 (尚缺)"]]))
    c2.metric("可調派供給", len([s for s in st.session_state.supplies if s.get("qty", 0) > 0]))
    c3.metric("自主認領紀錄", len(st.session_state.claims))

    st.info("Demo 說明：政府帳號以公務信箱/人工審核模擬藍勾勾；Email 若未設定 SMTP，會顯示在 Email 通知紀錄中。")

# --- 頁面 2：註冊 / 登入 ---
elif page == "👤 註冊 / 登入":
    st.title("👤 Sign Up / Login 身分管理")
    tab_login, tab_signup = st.tabs(["登入 Demo 帳號", "註冊新帳號"])

    with tab_login:
        user_options = {u["user_id"]: f"{u['name']}｜{u['role']}｜{u['verification_status']}" for u in st.session_state.users}
        selected_uid = st.selectbox("選擇登入身分", list(user_options.keys()), format_func=lambda x: user_options[x])
        if st.button("登入此帳號", type="primary"):
            st.session_state.current_user = next(u for u in st.session_state.users if u["user_id"] == selected_uid)
            st.success(f"已登入：{st.session_state.current_user['name']}")
            st.rerun()

        st.subheader("目前帳號清單")
        st.dataframe(pd.DataFrame(st.session_state.users), hide_index=True, use_container_width=True)

    with tab_signup:
        st.markdown("### 新增使用者")
        role = st.selectbox("身分角色", ROLE_OPTIONS)
        name = st.text_input("姓名 / 單位顯示名稱")
        email = st.text_input("Email（政府單位建議使用 gov.tw 公務信箱）")
        phone = st.text_input("聯絡電話")
        area = st.text_input("服務/所在行政區", placeholder="例如：花蓮縣壽豐鄉")
        org = st.text_input("所屬單位 / 組織")
        title = st.text_input("職稱", placeholder="例如：里長、承辦人、CSR窗口")
        uploaded_doc = st.file_uploader("證明文件（Demo 可選）：名片、公文、單位證明", type=["pdf", "png", "jpg", "jpeg"])

        if st.button("建立帳號", type="primary"):
            email_lower = email.lower()
            is_gov_email = any(domain in email_lower for domain in GOV_DOMAIN_HINTS)
            if role == "政府單位" and is_gov_email:
                verification_status = "✅ 已認證"
                blue_check = True
            elif role == "政府單位" and uploaded_doc is not None:
                verification_status = "🟡 待認證"
                blue_check = False
            else:
                verification_status = "⚪ 未認證" if role == "一般民眾" else "🟡 待認證"
                blue_check = False

            new_user = {
                "user_id": f"U{int(time.time()) % 100000:05d}",
                "name": name or "未命名使用者",
                "role": role,
                "email": email,
                "phone": phone,
                "area": area,
                "org": org,
                "title": title,
                "verification_status": verification_status,
                "blue_check": blue_check,
                "signup_time": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            st.session_state.users.append(new_user)
            st.session_state.current_user = new_user
            add_notification(f"👤 新帳號註冊：{new_user['name']}｜{verification_status}", "system")
            st.success(f"帳號建立完成：{verification_status}")
            st.rerun()

# --- 頁面 3：多模態轉譯 ---
elif page == "📥 多模態轉譯":
    st.title("📥 多模態轉譯：文字 / 圖片 → 結構化供需資料")
    col_in, col_out = st.columns(2)

    with col_in:
        uploaded_file = st.file_uploader("📸 上傳災情或物資照片（可選）", type=["jpg", "png", "jpeg"])
        raw_text_input = st.text_area("補充文字說明", placeholder="例如：我們需要抽水機 / 我們可以提供50名志工")
        st.caption("AI 會自動判斷是需求 Demand 或供給 Supply，並分類為有形、無形或金流資源。")

        if st.button("🧠 啟動 AI 解析", type="primary"):
            with st.spinner("AI 解析中..."):
                img_bytes = uploaded_file.getvalue() if uploaded_file else None
                mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
                text_to_send = raw_text_input if raw_text_input else "請根據圖片判斷災情與需求或供給。"
                result = extract_info_with_ai(raw_text=text_to_send, image_bytes=img_bytes, mime_type=mime_type)

                if "error" in result:
                    st.error("解析錯誤")
                    st.code(result["error"])
                else:
                    extracted = result.get("data", result)
                    is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
                    user = st.session_state.current_user
                    new_record = {
                        "id": f"{'D' if is_demand else 'S'}{int(time.time()) % 10000:04d}",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "source": "AI多模態轉譯",
                        "raw_text": text_to_send,
                        "status": "未處理" if is_demand else "可調派",
                        "verification_status": user.get("verification_status", "⚪ 未認證"),
                        "blue_check": user.get("blue_check", False)
                    }
                    new_record.update(extracted)
                    new_record = normalize_record(new_record, is_demand=is_demand)
                    if is_demand:
                        if not new_record.get("blue_check"):
                            new_record["verified_by"] = f"已通知 {new_record.get('location', '所在地')} 對應地方單位待認證"
                            new_record["verification_status"] = "🟡 待認證"
                        st.session_state.demands.append(new_record)
                        st.success("✅ 已寫入需求庫。")
                    else:
                        st.session_state.supplies.append(new_record)
                        st.success("✅ 已寫入供給庫。")
                    with col_out:
                        st.json(result)

# --- 頁面 4：前線對話通報 ---
elif page == "💬 前線對話通報":
    st.title("💬 前線防救災 AI 對話助理")
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_input := st.chat_input("請輸入通報內容或可提供資源..."):
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("AI 處理中..."):
                result = extract_info_with_ai(raw_text=user_input)
                if "error" not in result:
                    extracted = result.get("data", result)
                    is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
                    user = st.session_state.current_user
                    new_record = {
                        "id": f"{'D' if is_demand else 'S'}{int(time.time()) % 10000:04d}",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "source": "對話通報",
                        "raw_text": user_input,
                        "status": "未處理" if is_demand else "可調派",
                        "verification_status": user.get("verification_status", "⚪ 未認證"),
                        "blue_check": user.get("blue_check", False)
                    }
                    new_record.update(extracted)
                    new_record = normalize_record(new_record, is_demand=is_demand)

                    if is_demand:
                        if not new_record.get("blue_check"):
                            new_record["verification_status"] = "🟡 待認證"
                            new_record["verified_by"] = f"已通知 {new_record.get('location', '地方單位')} 待確認"
                        st.session_state.demands.append(new_record)
                    else:
                        st.session_state.supplies.append(new_record)

                    reply = f"""✅ 收到！已立案。
- 類型：{'需求 Demand' if is_demand else '供給 Supply'}
- 資源分類：{new_record.get('resource_type')} / {new_record.get('category')}
- 項目：{new_record.get('item')} x {new_record.get('qty')}
- 認證狀態：{get_badge(new_record)}
"""
                else:
                    reply = "抱歉，解析遇到問題，請重試，或改用表單建立資料。"
                st.markdown(reply)
                st.session_state.chat_history.append({"role": "assistant", "content": reply})

# --- 頁面 5：戰備資源池 ---
elif page == "📊 戰備資源池":
    st.title("📊 空間戰備資源池：分類 + 認證 + 供需狀態")

    map_data = []
    for d in st.session_state.demands:
        if d.get("lat") and d.get("lon"):
            map_data.append({"lat": d["lat"], "lon": d["lon"], "color": "#FF0000"})
    for s in st.session_state.supplies:
        if s.get("lat") and s.get("lon") and s.get("qty", 0) > 0:
            map_data.append({"lat": s["lat"], "lon": s["lon"], "color": "#00AA00"})

    if map_data:
        st.markdown("🔴 **紅色：需求點** ｜ 🟢 **綠色：供給點**")
        st.map(pd.DataFrame(map_data), color="color", zoom=6, use_container_width=True)

    st.divider()
    filter_type = st.selectbox("依資源型態篩選", ["全部"] + list(RESOURCE_TAXONOMY.keys()))
    trust_filter = st.checkbox("只顯示已認證資料")

    df_d = pd.DataFrame(st.session_state.demands)
    df_s = pd.DataFrame(st.session_state.supplies)
    if filter_type != "全部":
        df_d = df_d[df_d["resource_type"] == filter_type]
        df_s = df_s[df_s["resource_type"] == filter_type]
    if trust_filter:
        df_d = df_d[df_d["verification_status"] == "✅ 已認證"]
        df_s = df_s[df_s["verification_status"] == "✅ 已認證"]

    col_d, col_s = st.columns(2)
    with col_d:
        st.subheader("🚨 前線需求")
        show_cols = ["id", "location", "resource_type", "category", "item", "qty", "urgency", "verification_status", "verified_by", "matched_provider", "status"]
        st.dataframe(df_d[[c for c in show_cols if c in df_d.columns]], hide_index=True, use_container_width=True)
    with col_s:
        st.subheader("📦 後勤供給")
        show_cols = ["id", "provider", "location_current", "resource_type", "category", "item", "qty", "verification_status", "status"]
        st.dataframe(df_s[[c for c in show_cols if c in df_s.columns]], hide_index=True, use_container_width=True)

# --- 頁面 6：公開需求認領牆 ---
elif page == "📋 公開需求認領牆":
    st.title("📋 公開需求認領牆")
    st.caption("供給方可主動認領需求；可選擇只查看已認證需求，降低假資訊風險。")

    only_verified = st.checkbox("只看藍勾勾已認證需求", value=False)
    selected_type = st.selectbox("資源型態", ["全部"] + list(RESOURCE_TAXONOMY.keys()))

    demands = [d for d in st.session_state.demands if d["status"] in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    if only_verified:
        demands = [d for d in demands if d.get("verification_status") == "✅ 已認證"]
    if selected_type != "全部":
        demands = [d for d in demands if d.get("resource_type") == selected_type]

    if not demands:
        st.info("目前沒有符合條件的公開需求。")
    else:
        for d in demands:
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.markdown(f"### {d.get('item')} x {d.get('qty')}｜{d.get('location')}")
                    st.write(f"分類：**{d.get('resource_type')} / {d.get('category')}**")
                    st.write(f"認證：**{get_badge(d)}**｜認證來源：{d.get('verified_by', '尚未認證')}")
                    st.caption(f"原始通報：{d.get('raw_text')}")
                with c2:
                    st.metric("緊急程度", d.get("urgency", 3))
                    st.write(f"狀態：{d.get('status')}")
                with c3:
                    with st.form(f"claim_form_{d['id']}"):
                        default_name = st.session_state.current_user.get("name", "")
                        default_email = st.session_state.current_user.get("email", "")
                        provider_name = st.text_input("認領者", value=default_name, key=f"pn_{d['id']}")
                        provider_email = st.text_input("Email", value=default_email, key=f"pe_{d['id']}")
                        claim_qty = st.number_input("認領數量", min_value=1, max_value=max(1, int(d.get("qty", 1))), value=1, key=f"cq_{d['id']}")
                        note = st.text_area("備註", placeholder="例如：可今天下午送達", key=f"note_{d['id']}")
                        submitted = st.form_submit_button("🤝 我要認領")
                        if submitted:
                            claim_demand(d["id"], provider_name, provider_email, claim_qty, note)
                            st.rerun()

    st.divider()
    st.subheader("🤝 認領紀錄")
    if st.session_state.claims:
        st.dataframe(pd.DataFrame(st.session_state.claims), hide_index=True, use_container_width=True)
    else:
        st.caption("尚無認領紀錄。")

# --- 頁面 7：AI 調配引擎 ---
elif page == "🤖 AI 調配引擎":
    st.title("🤖 AI 調配引擎：地理 + 語意 + 分類 + 認證")
    if "success_msg" in st.session_state:
        st.success(st.session_state.success_msg)
        del st.session_state.success_msg

    pending_demands = [d for d in st.session_state.demands if d["status"] in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    available_supplies = [s for s in st.session_state.supplies if s.get("qty", 0) > 0]
    trusted_only = st.checkbox("媒合時只使用已認證供給", value=False)

    if pending_demands and available_supplies:
        col_match_opt, col_match_act = st.columns([1, 2])
        with col_match_opt:
            demand_options = {
                d["id"]: f"[{d['id']}] {d.get('location')}｜{d.get('resource_type')}/{d.get('category')}｜缺 {d.get('item')} x {d.get('qty')}｜{d.get('verification_status')}"
                for d in pending_demands
            }
            selected_demand_id = st.selectbox("🎯 選擇需求", options=list(demand_options.keys()), format_func=lambda x: demand_options[x])
            target_demand = next(d for d in pending_demands if d["id"] == selected_demand_id)
            st.info(f"需求認證：{get_badge(target_demand)}")
            match_btn = st.button("⚡ 啟動 AI 空間媒合", type="primary", use_container_width=True)

        with col_match_act:
            if match_btn:
                with st.spinner("AI 地理空間與資源分類媒合中..."):
                    match_results = ai_match_resources(target_demand, available_supplies, trusted_only=trusted_only)
                    if not match_results or (isinstance(match_results, list) and len(match_results) > 0 and "error" in match_results[0]):
                        st.warning("⚠️ 演算失敗或目前無適合資源。")
                        if match_results:
                            st.code(match_results[0].get("error", match_results[0]))
                    else:
                        for match in match_results:
                            supply_id = match.get("supply_id")
                            supply_info = next((s for s in available_supplies if s["id"] == supply_id), None)
                            if supply_info:
                                with st.container(border=True):
                                    st.markdown(f"#### 推薦來源：{supply_info.get('provider')} {('✅' if supply_info.get('blue_check') else '')}")
                                    st.write(f"分類：**{supply_info.get('resource_type')} / {supply_info.get('category')}**｜項目：{supply_info.get('item')}")
                                    st.write(f"供給認證：**{get_badge(supply_info)}**")
                                    st.progress(match.get("match_score", 0) / 100, text=f"契合度：{match.get('match_score', 0)} 分")
                                    expected_qty = min(int(target_demand.get("qty", 0)), int(supply_info.get("qty", 0)))
                                    st.write(f"📍 位置：{supply_info.get('location_current')}｜📦 預計調撥：{expected_qty} 件")
                                    st.info(f"💡 AI 理由：{match.get('reason')}")
                                    st.button("✅ 批准調度並寄送 Email", key=f"btn_{supply_id}", on_click=execute_dispatch, args=(target_demand["id"], supply_id, supply_info.get("provider")))
    else:
        st.info("目前沒有待處理需求，或後勤資源已耗盡。")

# --- 頁面 8：認證審核中心 ---
elif page == "✅ 認證審核中心":
    st.title("✅ 認證審核中心")
    user = st.session_state.current_user
    if user.get("role") != "政府單位" or not user.get("blue_check"):
        st.warning("此頁面建議由已認證政府單位使用。Demo 中可切換到『花蓮壽豐鄉公所』帳號體驗。")

    st.markdown("### 待認證需求")
    pending = [d for d in st.session_state.demands if d.get("verification_status") in ["🟡 待認證", "⚪ 未認證"]]
    if not pending:
        st.info("目前沒有待認證需求。")
    else:
        for d in pending:
            with st.container(border=True):
                st.markdown(f"#### {d.get('id')}｜{d.get('location')}｜{d.get('item')} x {d.get('qty')}")
                st.write(f"通報者：{d.get('requester')}｜Email：{d.get('requester_email')}")
                st.write(f"分類：{d.get('resource_type')} / {d.get('category')}｜緊急程度：{d.get('urgency')}")
                st.caption(f"原文：{d.get('raw_text')}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ 通過認證，給藍勾勾", key=f"verify_{d['id']}"):
                        verify_demand(d["id"], user.get("name", "政府單位"))
                        st.rerun()
                with c2:
                    if st.button("⚪ 標記未認證", key=f"unverify_{d['id']}"):
                        reject_or_mark_unverified(d["id"], user.get("name", "政府單位"))
                        st.rerun()

    st.divider()
    st.markdown("### 帳號認證概況")
    st.dataframe(pd.DataFrame(st.session_state.users), hide_index=True, use_container_width=True)

# --- 頁面 9：Email 通知紀錄 ---
elif page == "📧 Email 通知紀錄":
    st.title("📧 Email 通知紀錄")
    st.caption("若有設定 SMTP，系統會嘗試真正寄出；未設定時會保留 Demo 模擬寄信紀錄。")

    with st.expander("SMTP .env 設定範例"):
        st.code("""SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@gmail.com""")

    if st.session_state.email_logs:
        st.dataframe(pd.DataFrame(st.session_state.email_logs), hide_index=True, use_container_width=True)
        selected = st.selectbox("查看信件內容", range(len(st.session_state.email_logs)), format_func=lambda i: f"{st.session_state.email_logs[i]['time']}｜{st.session_state.email_logs[i]['to']}｜{st.session_state.email_logs[i]['subject']}")
        st.text_area("信件內容", st.session_state.email_logs[selected]["body"], height=250)
    else:
        st.info("尚無 Email 通知紀錄。請先進行 AI 調度或公開認領。")

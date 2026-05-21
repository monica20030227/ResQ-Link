import os
import time
import json
import base64
import smtplib
import random
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT", "587").isdigit() else 587
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "ㄑ")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

# =========================================================
# 0. Demo 常數設定
# =========================================================
RESOURCE_TYPES = {
    "有形資源": ["食物", "飲用水", "醫療用品", "生活用品", "家具", "救災工具", "交通工具", "重型機具", "其他"],
    "無形資源": ["人力", "志工", "專業技術", "醫療支援", "心理諮詢", "運輸協助", "其他"],
    "金流資源": ["現金捐款", "物資採購金", "專案補助", "其他"],
}
ROLE_LABELS = {
    "citizen": "一般民眾",
    "company": "公司/團體",
    "government": "政府單位",
    "admin": "平台管理員",
}
VERIFY_BADGE = {
    "verified": "✅ 已認證",
    "pending": "🟡 待認證",
    "unverified": "⚪ 未認證",
    "rejected": "🔴 已駁回",
}
CLAIM_STATUS = {
    "pending_match": "待系統媒合",
    "pending_gov_review": "待政府審核",
    "approved": "已核准並完成配對",
    "rejected": "已駁回",
}

SMART_MATCH_STATUS = {
    "pending_admin_review": "待管理員審核",
    "approved": "已核准並完成配對",
    "rejected": "已駁回",
    "expired": "已失效",
}

# =========================================================
# UI 輔助函數
# =========================================================
def get_status_badge(status):
    """回傳帶有 CSS 樣式的狀態標籤 HTML"""
    badges = {
        "verified": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>✅ 已認證</span>",
        "pending": "<span style='background-color:#fff3cd; color:#856404; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>⏳ 待審核</span>",
        "rejected": "<span style='background-color:#f8d7da; color:#721c24; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>❌ 已駁回</span>",
        "已處理": "<span style='background-color:#cce5ff; color:#004085; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🔄 處理中</span>",
        "已出貨": "<span style='background-color:#cce5ff; color:#004085; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🚚 配送中</span>",
        "已完成(收妥)": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🎉 任務結案</span>",
        "部分配對 (尚缺)": "<span style='background-color:#fff3cd; color:#856404; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>⚠️ 部分配對</span>",
        "可調派": "<span style='background-color:#d4edda; color:#155724; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>🟢 可調派</span>",
        "未處理": "<span style='background-color:#e2e3e5; color:#383d41; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;'>⚪ 未處理</span>"
    }
    return badges.get(status, f"<span style='background-color:#e2e3e5; color:#383d41; padding:3px 8px; border-radius:12px; font-size:12px;'>{status}</span>")
    
# =========================================================
# 1. Session State 初始化
# =========================================================
def now_str(fmt="%Y-%m-%d %H:%M"):
    return datetime.now().strftime(fmt)


def init_session_state():
    now = datetime.now()

    if "current_user" not in st.session_state:
        st.session_state.current_user = None

    # 手機 OTP 驗證暫存區：Demo 版存在 session_state；正式版建議改成 Redis/DB 並設定過期時間。
    if "otp_store" not in st.session_state:
        st.session_state.otp_store = {}

    if "users" not in st.session_state:
        st.session_state.users = [
            {
                "id": "U_ADMIN",
                "name": "平台管理員",
                "role": "admin",
                "email": "admin@resqlink.demo",
                "district": "全區",
                "village": "全區",
                "verified": True,
                "status": "active",
                "proof": "系統預設帳號",
            },
            {
                "id": "U_GOV_001",
                "name": "壽豐鄉公所承辦人",
                "role": "government",
                "email": "gov-shoufeng@gov.tw",
                "district": "花蓮縣壽豐鄉",
                "village": "全區",
                "verified": True,
                "status": "active",
                "proof": "公務信箱 + demo 白名單",
            },
            {
                "id": "U_GOV_002",
                "name": "仁愛鄉翠華村里幹事",
                "role": "government",
                "email": "gov-renai@gov.tw",
                "district": "南投縣仁愛鄉",
                "village": "翠華村",
                "verified": True,
                "status": "active",
                "proof": "公務信箱 + demo 白名單",
            },
            {
                "id": "U_CIT_001",
                "name": "壽豐居民小林",
                "role": "citizen",
                "email": "citizen@example.com",
                "district": "花蓮縣壽豐鄉",
                "village": "全區",
                "verified": False,
                "status": "active",
                "proof": "一般民眾註冊",
            },
            {
                "id": "U_COM_001",
                "name": "統一企業",
                "role": "company",
                "email": "supply@example.com",
                "district": "台南市永康區",
                "village": "全區",
                "verified": True,
                "status": "active",
                "proof": "企業統編 + demo 白名單",
            },
        ]

    # 補齊舊資料欄位，避免新增手機驗證後舊 demo 帳號缺欄位。
    for u in st.session_state.users:
        u.setdefault("phone", "")
        u.setdefault("phone_verified", True if u.get("id") in ["U_ADMIN", "U_GOV_001", "U_GOV_002", "U_CIT_001", "U_COM_001"] else False)

    if "demands" not in st.session_state:
        st.session_state.demands = [
            {
                "id": "D001",
                "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"),
                "source": "Threads",
                "requester_id": "U_CIT_001",
                "requester_name": "壽豐居民小林",
                "requester_email": "citizen@example.com",
                "district": "花蓮縣壽豐鄉",
                "village": "全區",
                "location": "花蓮縣壽豐鄉",
                "lat": 23.871,
                "lon": 121.508,
                "resource_type": "有形資源",
                "category": "救災工具",
                "item": "抽水機",
                "qty": 5,
                "urgency": 5,
                "status": "未處理",
                "matched_provider": "",
                "verification_status": "pending",
                "verified_by": "",
                "raw_text": "壽豐中山路這邊急需大型抽水機😭😭",
                "risk_flag": "",
            },
            {
                "id": "D002",
                "time": (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"),
                "source": "LINE群組",
                "requester_id": "U_GOV_002",
                "requester_name": "仁愛鄉翠華村里幹事",
                "requester_email": "gov-renai@gov.tw",
                "district": "南投縣仁愛鄉",
                "village": "翠華村",
                "location": "南投縣仁愛鄉翠華村",
                "lat": 24.025,
                "lon": 121.128,
                "resource_type": "有形資源",
                "category": "飲用水",
                "item": "礦泉水",
                "qty": 100,
                "urgency": 4,
                "status": "未處理",
                "matched_provider": "",
                "verification_status": "verified",
                "verified_by": "U_GOV_002",
                "raw_text": "仁愛鄉翠華村聯外道路中斷，急需礦泉水支援。",
                "risk_flag": "",
            },
        ]

    if "supplies" not in st.session_state:
        st.session_state.supplies = [
            {
                "id": "S001",
                "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
                "source": "企業信件",
                "provider_id": "U_COM_001",
                "provider": "統一企業",
                "provider_email": "supply@example.com",
                "district": "台南市永康區",
                "village": "全區",
                "location_current": "台南市永康區",
                "lat": 23.026,
                "lon": 120.254,
                "resource_type": "有形資源",
                "category": "飲用水",
                "item": "礦泉水",
                "qty": 500,
                "status": "可調派",
                "verification_status": "verified",
                "verified_by": "U_ADMIN",
                "raw_text": "本公司願捐贈500箱礦泉水，存放於永康物流中心。",
                "risk_flag": "",
            },
            {
                "id": "S002",
                "time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
                "source": "志工表單",
                "provider_id": "U_CIT_001",
                "provider": "吉普車救援隊",
                "provider_email": "citizen@example.com",
                "district": "花蓮縣壽豐鄉",
                "village": "全區",
                "location_current": "花蓮市區",
                "lat": 23.987,
                "lon": 121.601,
                "resource_type": "有形資源",
                "category": "救災工具",
                "item": "四輪傳動車與抽水機",
                "qty": 3,
                "status": "可調派",
                "verification_status": "pending",
                "verified_by": "",
                "raw_text": "花蓮在地車隊備有3台抽水機可支援涉水。",
                "risk_flag": "",
            },
        ]

    if "claims" not in st.session_state:
        st.session_state.claims = []

    # 系統自動掃描供需後產生的「智慧配對建議」
    # 與民眾/公司主動認領不同，這裡是平台主動發現可媒合組合，交給管理員審核。
    if "smart_matches" not in st.session_state:
        st.session_state.smart_matches = []

    if "notifications" not in st.session_state:
        st.session_state.notifications = []

    if "email_logs" not in st.session_state:
        st.session_state.email_logs = []

    if "audit_logs" not in st.session_state:
        st.session_state.audit_logs = []

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "assistant", "content": "您好！我是防救災通報機器人。請描述所在地、需求或可提供的資源。"}
        ]


def add_audit(action, detail):
    user = st.session_state.current_user or {"name": "未登入", "role": "guest"}
    st.session_state.audit_logs.insert(
        0,
        {
            "time": now_str("%Y-%m-%d %H:%M:%S"),
            "user": user.get("name", "未知"),
            "role": ROLE_LABELS.get(user.get("role", "guest"), user.get("role", "guest")),
            "action": action,
            "detail": detail,
        },
    )


def normalize_qty(value, default=1):
    try:
        value = int(value)
        return max(value, 1)
    except Exception:
        return default


def make_id(prefix):
    return f"{prefix}{int(time.time() * 1000) % 100000:05d}"


def get_current_user():
    return st.session_state.current_user


def is_logged_in():
    return st.session_state.current_user is not None


def can_gov_review(gov_user, record):
    """
    審查政府單位是否具備該筆紀錄的管轄權 (升級版：支援模糊行政區與全區互通機制)
    """
    if not gov_user or gov_user.get("role") != "government":
        return False
        
    # 平台管理員或設定為「全區」的最高指揮官直接放行
    if gov_user.get("district") == "全區":
        return True

    # 1. 💡 行政區雙向包含比對 (容錯「花蓮縣壽豐鄉」與「壽豐鄉」或「花蓮壽豐」)
    gov_dist = str(gov_user.get("district") or "").strip()
    rec_dist = str(record.get("district") or "").strip()
    
    if not gov_dist or not rec_dist:
        return False
        
    same_district = (gov_dist in rec_dist) or (rec_dist in gov_dist)

    # 2. 💡 村里範圍互通邏輯
    # 只要符合以下任一條件即具備管轄權：
    # - 政府官員是行政區總窗口 (gov_village 為 "全區" 或 空值)
    # - 民眾通報影響範圍涵蓋全區 (rec_village 為 "全區" 或 空值，基層官員皆應能審查)
    # - 政府官員的轄區里與民眾通報的里完全一致
    gov_village = str(gov_user.get("village") or "全區").strip()
    rec_village = str(record.get("village") or "全區").strip()
    
    same_village = (gov_village in ["全區", ""]) or (rec_village in ["全區", ""]) or (gov_village == rec_village)

    return same_district and same_village


def badge_text(status):
    return VERIFY_BADGE.get(status, "⚪ 未認證")


def normalize_phone(phone):
    """簡易手機格式整理：保留 + 與數字，Demo 可支援 09xx 或 +886。"""
    phone = str(phone or "").strip()
    phone = re.sub(r"[^0-9+]", "", phone)
    return phone


def is_valid_phone(phone):
    phone = normalize_phone(phone)
    # 台灣手機常見：09xxxxxxxx；也允許國際格式 +8869xxxxxxxx
    return bool(re.match(r"^09\d{8}$", phone) or re.match(r"^\+8869\d{8}$", phone))


def send_phone_otp(phone):
    """
    Demo OTP：產生 6 碼驗證碼並寫入 session_state。
    注意：OTP 不寫入全站通知中心，避免其他使用者在側邊欄看到驗證碼。
    正式部署若要真的傳 SMS，可串 Twilio/三竹/中華電信簡訊 API。
    """
    phone = normalize_phone(phone)
    otp = f"{random.randint(0, 999999):06d}"
    st.session_state.otp_store[phone] = {
        "otp": otp,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(minutes=5),
        "verified": False,
        "attempts": 0,
    }
    # Demo 版只把 OTP 回傳給目前正在註冊的人；不放進全站通知中心。
    add_audit("發送手機 OTP", f"phone={phone}")
    return otp


def verify_phone_otp(phone, otp_input):
    phone = normalize_phone(phone)
    otp_input = str(otp_input or "").strip()
    record = st.session_state.otp_store.get(phone)
    if not record:
        return False, "尚未發送 OTP，請先按『發送手機 OTP』。"
    if datetime.now() > record.get("expires_at"):
        return False, "OTP 已過期，請重新發送。"
    record["attempts"] = int(record.get("attempts", 0)) + 1
    if record["attempts"] > 5:
        return False, "嘗試次數過多，請重新發送 OTP。"
    if otp_input != record.get("otp"):
        return False, "OTP 驗證碼不正確。"
    record["verified"] = True
    return True, "手機號碼已完成 OTP 驗證。"

# =========================================================
# 2. Email / 通知
# =========================================================
def send_email(to_email, subject, body):
    """Demo 版：若 .env 有 SMTP 設定就真的寄信，否則只寫入 email_logs。"""
    log = {
        "time": now_str("%Y-%m-%d %H:%M:%S"),
        "to": to_email or "未提供",
        "subject": subject,
        "body": body,
        "status": "demo_log_only",
    }

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD and to_email:
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
            log["status"] = "sent"
        except Exception as e:
            log["status"] = f"failed: {e}"

    st.session_state.email_logs.insert(0, log)
    return log["status"]


def add_notification(msg, notif_type="system"):
    st.session_state.notifications.insert(
        0,
        {"time": now_str("%H:%M:%S"), "msg": msg, "type": notif_type},
    )


def notify_claim_result(demand, supply, claim, result="approved"):
    if result == "approved":
        subject = "【ResQ-Link】救災資源認領已核准並完成配對"
        body_d = f"""您好，您的需求已成功完成配對。

需求編號：{demand.get('id')}
需求項目：{demand.get('item')}
配對來源：{supply.get('provider')}
支援數量：{claim.get('claim_qty')}
目前狀態：{demand.get('status')}

請保持聯絡暢通。"""
        body_s = f"""您好，您的認領申請已核准。

需求編號：{demand.get('id')}
需求地點：{demand.get('location')}
支援項目：{supply.get('item')}
支援數量：{claim.get('claim_qty')}
需求認證狀態：{badge_text(demand.get('verification_status'))}

請依照平台資訊與需求方聯繫。"""
        send_email(demand.get("requester_email"), subject, body_d)
        send_email(supply.get("provider_email"), subject, body_s)
        add_notification(f"📧 已通知需求方與供給方：{demand.get('item')} x {claim.get('claim_qty')}", "email")
    else:
        subject = "【ResQ-Link】救災資源認領申請未通過"
        body = f"""您好，您的認領申請未通過。

申請編號：{claim.get('id')}
原因：{claim.get('review_note', '未填寫')}

您仍可重新提出其他認領申請。"""
        send_email(supply.get("provider_email"), subject, body)
        add_notification(f"📧 已通知認領方申請未通過：{claim.get('id')}", "email")

# =========================================================
# 3. AI 引擎
# =========================================================
def extract_info_with_ai(raw_text=None, image_bytes=None, mime_type="image/jpeg"):
    if not GROQ_API_KEY: return {"error": "尚未設定 GROQ_API_KEY"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", max_retries=1, timeout=15.0)
        
        system_prompt = """
        你是一個專業防災調度員與台灣地理資訊專家。請判斷輸入是「Demand」或「Supply」，並將其精準萃取為 JSON 格式。
        
        ⚠️【重要：台灣地標、學校與建築物逆向解算規則】：
        當輸入文字或圖片中包含台灣的學校、特定地標、車站、體育館、政府機關或物流中心（例如：「國立台灣大學」、「壽豐國中」、「台北101」、「花蓮車站」、「林口中儲倉」）時，你必須：
        1. 運用你的地理知識庫，精準推導出該地標所屬的完整台灣行政區（格式必須包含完整縣市與鄉鎮市區，例如：「臺北市大安區」、「花蓮縣壽豐鄉」、「新北市林口區」），並填入 JSON 的 "district" 欄位。切勿填寫"未知"或留空！
        2. 精準估算該地標的真實經緯度，填入 "lat" 與 "lon" 浮點數欄位。嚴禁直接盲目填寫 center 點 23.5/121.0，必須盡量貼近該著名地標的實際地理坐標。

        ⚠️【邊緣隱私防護與 DLP 攔截機制】：
        若圖片或文字中包含清晰可辨識之人物臉部、傷患、遺體、個人身分證件或敏感財務資訊，請在 JSON 中將 "risk_flag" 設為 "包含敏感個資/人像"，並停止描述人體與個資細節，僅針對物資與災情環境進行萃取。若無敏感資訊，risk_flag 請填空字串 ""。

        回傳格式請嚴格遵循以下 JSON 結構：
        {
          "info_type": "Demand 或 Supply",
          "data": {
              "location": "輸入的地地點、學校或完整地址",
              "provider": "若是Supply填提供者，Demand留空",
              "location_current": "若是Supply填所在地點或地標，Demand留空",
              "category": "物資類別", 
              "item": "具體物品", 
              "qty": 數量, 
              "urgency": 緊急度1-5,
              "lat": 緯度浮點數, 
              "lon": 經度浮點數,
              "district": "推導出的完整台灣行政區(如：花蓮縣壽豐鄉)",
              "risk_flag": "敏感個資警告或空字串"
          }
        }
        """
        messages = [{"role": "system", "content": system_prompt}]
        if image_bytes:
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            messages.append({"role": "user", "content": [{"type": "text", "text": str(raw_text)}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]})
            model_name = "meta-llama/llama-4-scout-17b-16e-instruct"
        else:
            messages.append({"role": "user", "content": str(raw_text)})
            model_name = "llama-3.3-70b-versatile"
            
        res = client.chat.completions.create(model=model_name, messages=messages, temperature=0.0)
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find('{')
        end_idx = raw_output.rfind('}')
        if start_idx != -1 and end_idx != -1: return json.loads(raw_output[start_idx:end_idx+1])
        return {"error": "格式異常", "raw": raw_output}
    
    except Exception as e: 
        error_msg = str(e).lower()
        if "429" in error_msg or "rate limit" in error_msg or "timeout" in error_msg:
            return {"error": "API_RATE_LIMIT"}
        return {"error": str(e)}
# ==========================================
# 3.5 災情去重與合併防護 (Deduplication)
# ==========================================
def check_duplicate_demand(district, item):
    """檢查過去 12 小時內，同一行政區是否有高度相似的物資需求"""
    if not district or not item: return None
    
    # 簡單的關鍵字模糊比對
    keywords = set(item.replace("需要", "").replace("急需", "").split())
    
    for d in st.session_state.demands:
        if d.get("district") == district and d.get("status") in ["未處理", "部分配對 (尚缺)"]:
            existing_item = d.get("item", "")
            if any(k in existing_item for k in keywords if len(k) >= 2):
                return d
    return None
# =========================================================
# 4. 核心業務邏輯
# =========================================================
def simple_match_check(demand, supply, claim_qty):
    """
    使用 Groq AI 動態評估認領申請的合理性與分數 (取代舊版寫死的 if-else)
    """
    if claim_qty <= 0:
        return False, 0, "認領數量需大於 0"
    if supply.get("qty", 0) < claim_qty:
        return False, 0, "供給方庫存不足，無法認領該數量"
    if demand.get("qty", 0) <= 0:
        return False, 0, "需求已被滿足"
        
    if not GROQ_API_KEY:
        return True, 60, "未設定 API Key，系統給予基礎及格分待人工審核"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        
        prompt = f"""
        你是一個高階防災資源審查 AI。
        有一筆民眾/企業發起的「資源認領申請」，請評估供給方是否適合滿足需求方。
        
        【需求資訊】：分類({demand.get('category')}) / 品項({demand.get('item')}) / 地區({demand.get('district')}) / 認證狀態({demand.get('verification_status')})
        【供給資訊】：分類({supply.get('category')}) / 品項({supply.get('item')}) / 地區({supply.get('district')}) / 認證狀態({supply.get('verification_status')})
        【欲認領數量】：{claim_qty}
        
        請依據「品項語意是否吻合」、「地理位置運送難易度」、「雙方認證可信度」給予 0~100 的綜合評分。
        若分數 >= 45 視為及格 (passed: true)。
        
        請嚴格輸出 JSON 格式：
        {{
            "passed": true 或 false,
            "score": 整數分數,
            "reason": "詳細的評估理由"
        }}
        """
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find("{")
        end_idx = raw_output.rfind("}")
        if start_idx != -1 and end_idx != -1:
            data = json.loads(raw_output[start_idx : end_idx + 1])
            return data.get("passed", False), data.get("score", 0), data.get("reason", "AI 評估完成")
        return False, 0, "AI 格式回傳異常"
    except Exception as e:
        return False, 0, f"AI 評估出錯: {str(e)}"



def smart_match_exists(demand_id, supply_id):
    """避免同一組需求/供給被重複產生智慧配對建議。"""
    for m in st.session_state.smart_matches:
        if (
            m.get("demand_id") == demand_id
            and m.get("supply_id") == supply_id
            and m.get("status") == "pending_admin_review"
        ):
            return True
    return False


def generate_smart_match_suggestions(min_score=45, only_verified_demand=False, only_verified_supply=False):
    """
    自動掃描全平台的需求與供給。
    若資源型態、分類、品項、數量與地區等條件達到門檻，
    就建立一筆「智慧配對建議」，提供平台管理員審核。
    """
    created = 0
    candidates = []

    active_demands = [
        d for d in st.session_state.demands
        if d.get("status") in ["未處理", "部分配對 (尚缺)"]
        and int(d.get("qty", 0)) > 0
        and d.get("verification_status") != "rejected"
    ]
    active_supplies = [
        s for s in st.session_state.supplies
        if int(s.get("qty", 0)) > 0
        and s.get("status") not in ["已駁回", "已下架", "已指派 (無庫存)"]
        and s.get("verification_status") != "rejected"
    ]

    if only_verified_demand:
        active_demands = [d for d in active_demands if d.get("verification_status") == "verified"]
    if only_verified_supply:
        active_supplies = [s for s in active_supplies if s.get("verification_status") == "verified"]

    for d in active_demands:
        for s in active_supplies:
            if smart_match_exists(d.get("id"), s.get("id")):
                continue

            suggested_qty = min(int(d.get("qty", 0)), int(s.get("qty", 0)))
            passed, score, reason = simple_match_check(d, s, suggested_qty)

            if passed and score >= min_score:
                candidates.append((score, d, s, suggested_qty, reason))

    candidates = sorted(candidates, key=lambda x: x[0], reverse=True)

    for score, d, s, suggested_qty, reason in candidates:
        # 使用需求ID + 供給ID + created 序號建立唯一 ID，避免同一毫秒產生重複 ID
        smart_match = {
            "id": f"M_{d.get('id')}_{s.get('id')}_{int(time.time() * 1000)}_{created}",
            "time": now_str(),
            "demand_id": d.get("id"),
            "supply_id": s.get("id"),
            "suggested_qty": suggested_qty,
            "match_score": score,
            "match_reason": reason,
            "status": "pending_admin_review",
            "reviewer": "",
            "review_note": "",
            "review_time": "",
        }
        st.session_state.smart_matches.insert(0, smart_match)
        created += 1

    if created > 0:
        add_notification(f"🧠 系統產生 {created} 筆智慧配對建議，待平台管理員審核。", "smart_match")
        add_audit("產生智慧配對建議", f"新增 {created} 筆，門檻 {min_score}")
    else:
        add_audit("產生智慧配對建議", f"沒有新增建議，門檻 {min_score}")

    return created


def approve_smart_match(match_id, note=""):
    """管理員核准智慧配對建議後，才正式扣庫存、更新需求並通知雙方。"""
    m = next((x for x in st.session_state.smart_matches if x.get("id") == match_id), None)
    if not m:
        return False, "找不到智慧配對建議"

    d = next((x for x in st.session_state.demands if x.get("id") == m.get("demand_id")), None)
    s = next((x for x in st.session_state.supplies if x.get("id") == m.get("supply_id")), None)

    if not d or not s:
        m["status"] = "expired"
        m["review_note"] = "需求或供給資料已不存在"
        return False, "需求或供給資料已不存在"

    transfer_qty = min(int(m.get("suggested_qty", 0)), int(d.get("qty", 0)), int(s.get("qty", 0)))
    if transfer_qty <= 0:
        m["status"] = "expired"
        m["review_note"] = "需求或供給數量已不足"
        return False, "需求或供給數量已不足"

    claim = {
        "id": make_id("C"),
        "time": now_str(),
        "claimant_id": s.get("provider_id"),
        "claimant_name": s.get("provider"),
        "claimant_role": "system_smart_match",
        "demand_id": d.get("id"),
        "supply_id": s.get("id"),
        "claim_qty": transfer_qty,
        "match_score": m.get("match_score", 0),
        "match_reason": m.get("match_reason", ""),
        "status": "pending_gov_review",
        "note": "由系統智慧配對產生，平台管理員核准",
        "reviewer": "",
        "review_note": note or "平台管理員核准智慧配對",
        "review_time": "",
    }
    st.session_state.claims.insert(0, claim)

    ok = execute_dispatch(
        d.get("id"),
        s.get("id"),
        s.get("provider"),
        transfer_qty,
        claim_id=claim.get("id"),
    )

    if ok:
        user = get_current_user() or {"name": "平台管理員"}
        m["status"] = "approved"
        m["reviewer"] = user.get("name")
        m["review_note"] = note or "平台管理員核准智慧配對"
        m["review_time"] = now_str()
        add_audit("核准智慧配對", f"{match_id} / {d.get('id')} ← {s.get('id')} / 數量 {transfer_qty}")
        return True, "已核准並完成配對"

    return False, "配對失敗"


def reject_smart_match(match_id, note=""):
    m = next((x for x in st.session_state.smart_matches if x.get("id") == match_id), None)
    if not m:
        return False
    user = get_current_user() or {"name": "平台管理員"}
    m["status"] = "rejected"
    m["reviewer"] = user.get("name")
    m["review_note"] = note or "平台管理員駁回智慧配對"
    m["review_time"] = now_str()
    add_audit("駁回智慧配對", f"{match_id} / {m['review_note']}")
    return True


def execute_dispatch(demand_id, supply_id, provider_name, transfer_qty=None, claim_id=None):
    demand_info = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    supply_info = next((s for s in st.session_state.supplies if s["id"] == supply_id), None)
    if not demand_info or not supply_info:
        return False

    if transfer_qty is None:
        transfer_qty = min(demand_info.get("qty", 0), supply_info.get("qty", 0))
    transfer_qty = normalize_qty(transfer_qty)
    transfer_qty = min(transfer_qty, demand_info.get("qty", 0), supply_info.get("qty", 0))
    if transfer_qty <= 0:
        return False

    demand_info["qty"] -= transfer_qty
    if demand_info.get("matched_provider"):
        demand_info["matched_provider"] += f", {provider_name}({transfer_qty}件)"
    else:
        demand_info["matched_provider"] = f"{provider_name}({transfer_qty}件)"
    demand_info["status"] = "已完成配對" if demand_info["qty"] <= 0 else "部分配對 (尚缺)"

    supply_info["qty"] -= transfer_qty
    supply_info["status"] = "已指派 (無庫存)" if supply_info["qty"] <= 0 else "可調派 (有剩餘)"

    msg_to_demand = f"📲 已指派【{provider_name}】提供 {transfer_qty} 件 {demand_info.get('item')} 至 {demand_info.get('location')}。"
    msg_to_supply = f"📲 請協助提供 {transfer_qty} 件 {supply_info.get('item')} 至 {demand_info.get('location')}。"
    add_notification(msg_to_demand, "demand")
    add_notification(msg_to_supply, "supply")

    if claim_id:
        claim = next((c for c in st.session_state.claims if c["id"] == claim_id), None)
        if claim:
            claim["status"] = "approved"
            claim["review_time"] = now_str("%Y-%m-%d %H:%M")
            claim["review_note"] = claim.get("review_note", "政府/管理員審核通過")
            notify_claim_result(demand_info, supply_info, claim, result="approved")

    add_audit("完成資源配對", f"{demand_id} ← {supply_id}，數量 {transfer_qty}")
    return True


def submit_claim(demand, supply, claim_qty, note):
    user = get_current_user()
    if not user:
        st.error("請先登入後再認領。")
        return

    passed, score, reason = simple_match_check(demand, supply, claim_qty)
    status = "pending_gov_review" if passed else "rejected"
    claim = {
        "id": make_id("C"),
        "time": now_str(),
        "claimant_id": user.get("id"),
        "claimant_name": user.get("name"),
        "claimant_role": user.get("role"),
        "demand_id": demand.get("id"),
        "supply_id": supply.get("id"),
        "claim_qty": claim_qty,
        "match_score": score,
        "match_reason": reason,
        "status": status,
        "note": note,
        "reviewer": "",
        "review_note": "" if passed else "系統媒合未通過，請確認資源分類、品項與庫存。",
        "review_time": "",
    }
    st.session_state.claims.insert(0, claim)

    if passed:
        add_notification(f"🤝 新認領申請待審核：{user.get('name')} → {demand.get('item')} x {claim_qty}", "claim")
        add_audit("提出認領申請", f"{claim['id']} 媒合分數 {score}")
        st.success("已送出認領申請，系統媒合通過，等待政府單位或管理員審核。")
    else:
        add_audit("認領申請被系統擋下", f"{claim['id']}，原因：{reason}")
        st.error(f"系統媒合未通過：{reason}")

# =========================================================
# 5. UI Helper
# =========================================================
def login_panel():
    st.title("🧩 ResQ-Link 可信任災害資源分配平台")
    st.caption("請先選擇登入身分。Demo 版不需密碼；註冊時會加入手機號碼與 OTP 驗證流程。")

    col1, col2, col3, col4 = st.columns(4)
    role_cards = [
        ("citizen", "👤 一般民眾", "提出需求、提供小量物資、認領需求"),
        ("company", "🏢 公司/團體", "建立供給、認領需求、查看配對"),
        ("government", "🏛️ 政府單位", "審核同區需求、審核認領申請"),
        ("admin", "🛡️ 平台管理員", "總控帳號、資料、審核、異常紀錄"),
    ]
    cols = [col1, col2, col3, col4]
    for col, (role, title, desc) in zip(cols, role_cards):
        with col:
            st.container(border=True).markdown(f"### {title}\n{desc}")

    role = st.selectbox("登入身分", list(ROLE_LABELS.keys()), format_func=lambda x: ROLE_LABELS[x])
    users = [u for u in st.session_state.users if u["role"] == role and u["status"] == "active"]
    if not users:
        st.warning("此角色目前沒有可登入帳號，請先註冊。")
    else:
        selected_user_id = st.selectbox(
            "選擇 Demo 帳號",
            [u["id"] for u in users],
            format_func=lambda uid: next(
                f"{u['name']}｜手機{'✅' if u.get('phone_verified') else '⚪'}"
                for u in users if u["id"] == uid
            ),
        )
        if st.button("登入", type="primary"):
            selected_user = next(u for u in users if u["id"] == selected_user_id)
            st.session_state.current_user = selected_user
            add_audit("登入系統", f"角色：{ROLE_LABELS[role]}")
            st.rerun()

    st.divider()
    with st.expander("➕ 註冊新帳號（含企業防偽與手機驗證）"):
        st.info("流程：填寫資料 → 企業驗證統編 / 民眾發送 OTP → 送出註冊。")
        with st.form("signup_form"):
            new_role = st.selectbox("帳號類型", ["citizen", "company", "government"], format_func=lambda x: ROLE_LABELS[x])
            name = st.text_input("姓名 / 單位名稱")
            
            # 💡 新增：企業專屬的統一編號欄位
            vat_number = ""
            if new_role == "company":
                vat_number = st.text_input("統一編號 (8碼數字)", placeholder="例如：16098128 (統一企業)")
                
            email = st.text_input("Email")
            phone = st.text_input("手機號碼", placeholder="例如：0912345678")
            district = st.text_input("行政區", placeholder="例如：花蓮縣壽豐鄉")
            village = st.text_input("村里", value="全區")
            proof = st.text_area("證明資料", placeholder="政府填公務信箱；企業統編系統將自動驗證；民眾填聯絡資訊。")
            otp_code = st.text_input("手機 OTP 驗證碼", placeholder="請輸入 6 碼驗證碼 (企業不強制)")

            col_otp, col_submit = st.columns(2)
            send_otp_btn = col_otp.form_submit_button("📱 發送手機 OTP")
            submitted = col_submit.form_submit_button("✅ 送出註冊", type="primary")

        phone_norm = normalize_phone(phone)

        if send_otp_btn:
            if not phone_norm or not is_valid_phone(phone_norm):
                st.error("請輸入有效手機號碼。")
            else:
                otp = send_phone_otp(phone_norm)
                st.success(f"OTP 已送出至 {phone_norm}。Demo 驗證碼：{otp}")

        if submitted:
            if not name or not email or not district:
                st.error("請至少填寫名稱、Email、行政區。")
                return
                
            # 💡 企業防偽審查：模擬經濟部商業司 API
            if new_role == "company":
                if not re.match(r"^\d{8}$", vat_number):
                    st.error("❌ 企業註冊請填寫正確的 8 碼統一編號！")
                    return
                with st.spinner("🔄 正在向經濟部商業司 API 驗證統一編號..."):
                    time.sleep(1.5) # 模擬 API 延遲
                st.success(f"✅ 統編 {vat_number} 驗證成功！")
                proof = f"[統編 {vat_number} API驗證通過] " + proof

            if new_role != "company" and not is_valid_phone(phone_norm):
                st.error("手機號碼格式不正確。")
                return

            if new_role != "company" and otp_code:
                ok, msg = verify_phone_otp(phone_norm, otp_code)
                if not ok:
                    st.error(msg)
                    return

            verified = False
            status = "pending" if new_role in ["government"] else "active"
            
            new_user = {
                "id": make_id("U"),
                "name": name,
                "role": new_role,
                "email": email,
                "phone": phone_norm,
                "phone_verified": bool(otp_code) or new_role == "company",
                "district": district,
                "village": village or "全區",
                "verified": new_role == "company", # 企業統編通過直接先視為 verified
                "status": status,
                "proof": proof,
            }
            st.session_state.users.append(new_user)
            add_audit("新帳號註冊", f"{name} / {ROLE_LABELS[new_role]}")
            st.success("註冊完成，可回上方登入。")

def sidebar_layout():
    user = get_current_user()
    with st.sidebar:
        st.title("🧩 ResQ-Link")
        if user:
            badge = "✅" if user.get("verified") else "⚪"
            st.success(f"{badge} {user.get('name')}\n\n{ROLE_LABELS.get(user.get('role'))}")
            st.caption(f"行政區：{user.get('district')} / {user.get('village')}")
            st.caption(f"手機：{user.get('phone', '未填')} / {'已驗證' if user.get('phone_verified') else '未驗證'}")
            if st.button("登出"):
                add_audit("登出系統", user.get("name"))
                st.session_state.current_user = None
                st.rerun()

        st.divider()
        st.subheader("🔔 配對與系統通知")
        if not st.session_state.notifications:
            st.caption("目前無最新通知。")
        else:
            for notif in st.session_state.notifications[:5]:
                st.markdown(f"<div style='border-left:4px solid #888;padding-left:10px;margin-bottom:8px;font-size:0.85em;'><b>{notif['time']}</b><br>{notif['msg']}</div>", unsafe_allow_html=True)


def resource_selectors(prefix=""):
    resource_type = st.selectbox("資源型態", list(RESOURCE_TYPES.keys()), key=f"{prefix}_rtype")
    category = st.selectbox("資源分類", RESOURCE_TYPES[resource_type], key=f"{prefix}_cat")
    return resource_type, category


def demand_card(d):
    st.markdown(f"### {badge_text(d.get('verification_status'))} [{d.get('id')}] {d.get('item')} x {d.get('qty')}")
    st.write(f"📍 {d.get('location')}｜分類：{d.get('resource_type')} / {d.get('category')}｜緊急度：{d.get('urgency')}")
    st.caption(f"提出者：{d.get('requester_name')}｜狀態：{d.get('status')}｜已配對：{d.get('matched_provider') or '無'}")
    if d.get("risk_flag"):
        st.warning(f"異常標記：{d.get('risk_flag')}")

# =========================================================
# 6. Pages
# =========================================================
def page_home():
    st.title("🏠 ResQ-Link：可信任災害資源分配平台")
    st.markdown(
        """
### 系統核心
本平台把災害期間的需求與供給分成 **有形資源、無形資源、金流資源**，並加入 **身分認證、地方政府審核、民眾/公司認領、管理員控管、Email 通知**。

### 角色分工
- 👤 **一般民眾**：提出需求、提供物資、認領需求，但重要配對需審核。
- 🏢 **公司/團體**：建立大量供給，認領公開需求。
- 🏛️ **政府單位**：審核同一行政區或村里的民眾需求與認領申請。
- 🛡️ **平台管理員**：控管帳號、資料、審核、異常紀錄與全平台狀態。
"""
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("需求數", len(st.session_state.demands))
    col2.metric("供給數", len(st.session_state.supplies))
    col3.metric("認領申請", len(st.session_state.claims))
    col4.metric("待審帳號", len([u for u in st.session_state.users if u.get("status") == "pending"]))


def page_submit_demand():
    user = get_current_user()
    st.title("📣 提出需求 (備用表單)")
    st.caption("建議優先使用左側『💬 智慧對話通報』。本表單支援輸入學校或知名地標，AI 將自動為您解析行政區與座標。")
    
    with st.form("demand_form"):
        # 💡 UI 修正：不再強行預填 user.get("district") 避免誤導，改用 placeholder 引導使用者輸入真正的物資需求地
        location = st.text_input("📍 需求地點 (可填寫完整地址、學校名稱或地標)", value="", placeholder="例如：壽豐國中、台灣大學體育館、台北101 或 完整地址", help="可以填寫具體地址或知名地標、學校，AI 將自動辨識所屬行政區與座標。", key="demand_location")
        
        resource_type, category = resource_selectors("demand")
        
        item = st.text_input("📦 需求品項", placeholder="範例：大型抽水機、礦泉水、睡袋", help="請具體說明需要的物資名稱，切勿填寫模糊字眼。", key="demand_item")
        qty = st.number_input("🔢 需求數量", min_value=1, value=1, help="必須大於 0 的整數。", key="demand_qty")
        urgency = st.slider("🚨 緊急程度 (1最低 - 5最高)", 1, 5, 3, help="5分為危及生命財產安全，1分為預防性儲備。", key="demand_urgency")
        raw_text = st.text_area("📝 補充說明 (選填)", placeholder="例如：道路中斷，僅能以直升機或輕裝徒步進入。", key="demand_raw_text")
        
        submitted = st.form_submit_button("🚀 送出需求", type="primary")

    if submitted:
        if not item.strip() or not location.strip():
            st.error("❌ 送出失敗：『需求地點』與『需求品項』為必填欄位，不得為空。")
            return
            
        with st.spinner("🧠 AI 正在辨識地標並精準定位座標..."):
            # 餵給 AI 強調這是台灣的地標
            ai_geo_result = extract_info_with_ai(raw_text=f"請精準解析出此台灣地點或地標的所屬行政區與經緯度：{location}")
            extracted = ai_geo_result.get("data", ai_geo_result)
            
            auto_district = extracted.get("district")
            auto_lat = extracted.get("lat", 23.8)
            auto_lon = extracted.get("lon", 121.0)
            
            # 💡 權責安全機制：若且唯若 AI 遭遇極端生僻字或完全認不出行政區時，才降級退守至使用者本人的註冊地
            if not auto_district or auto_district in ["未知", "無", ""]:
                auto_district = user.get("district", "全區")
        
        verification_status = "verified" if user.get("role") == "government" and user.get("verified") else "pending"
        demand = {
            "id": make_id("D"), "time": now_str(), "source": "平台表單",
            "requester_id": user.get("id"), "requester_name": user.get("name"), "requester_email": user.get("email"),
            "district": auto_district, "village": user.get("village", "全區"),
            "location": location, "lat": auto_lat, "lon": auto_lon,
            "resource_type": resource_type, "category": category, "item": item, "qty": int(qty),
            "urgency": urgency, "status": "未處理", "matched_provider": "",
            "verification_status": verification_status, "verified_by": user.get("id") if verification_status == "verified" else "",
            "raw_text": raw_text, "risk_flag": extracted.get("risk_flag", ""),
        }
        st.session_state.demands.insert(0, demand)
        st.success(f"✅ 需求已成功送出！案件編號：{demand['id']}。AI 已成功將地標『{location}』解析至【{auto_district}】，經緯度座標：({auto_lat}, {auto_lon})。")


def page_submit_supply():
    user = get_current_user()
    st.title("📦 建立供給 (支援企業批次建檔)")
    st.caption("大型企業可使用 ERP 批次匯入；地點請填寫『物資實際存放倉庫或地標』，系統將以此計算運送距離。")
    
    if "preview_supplies" not in st.session_state:
        st.session_state.preview_supplies = None
        
    tab1, tab2 = st.tabs(["✍️ 單筆手動建檔", "🤖 ERP/盤點清單 AI 批次匯入"])
    
    with tab1:
        with st.form("supply_form"):
            col_a, col_b = st.columns(2)
            with col_a:
                provider = st.text_input("🏢 提供者名稱", value=user.get("name", ""), placeholder="範例：統一企業、吉普車救援隊", key="supply_provider")
            with col_b:
                # 💡 UI 修正：清空預填，使用明確定標提示語
                location_current = st.text_input("📍 物資實際存放地點 (可填學校、特定倉庫或地標)", value="", placeholder="例如：花蓮車站、林口物流中心、壽豐國中體育館", help="請填寫『物資當下所在位置』，AI將據此計算運送距離。", key="supply_location")
            
            has_logistics = st.radio("🚚 物流配送能力", ["✅ 自有車隊/配合物流，可直接運送至災區", "❌ 無運輸能力，需平台媒合外部志工車隊載運"], key="supply_logistics")
            
            col_c, col_d, col_e = st.columns([1.5, 2, 1])
            with col_c:
                resource_type, category = resource_selectors("supply")
            with col_d:
                item = st.text_input("📦 可提供品項", placeholder="範例：礦泉水、發電機", key="supply_item")
            with col_e:
                qty = st.number_input("🔢 可提供數量", min_value=1, value=1, key="supply_qty")
                
            raw_text = st.text_area("📝 補充說明 (選填)", placeholder="例如：效期至 2027 年底。", key="supply_raw_text")
            submitted = st.form_submit_button("🚀 建立單筆供給", type="primary")

        if submitted:
            if not item.strip() or not provider.strip() or not location_current.strip():
                st.error("❌ 送出失敗：『提供者名稱』、『物資存放地點』與『品項』為必填。")
                return
            with st.spinner("🧠 AI 正在解析物資存放地與地標座標..."):
                ai_geo_result = extract_info_with_ai(raw_text=f"請精準解析出此台灣地點或地標的所屬行政區與經緯度：{location_current}")
                geo_data = ai_geo_result.get("data", ai_geo_result)
                
                lat = geo_data.get("lat", 23.8)
                lon = geo_data.get("lon", 121.0)
                district = geo_data.get("district")
                
                # 💡 降級備援：若 AI 無法識別特殊地名，才使用使用者本身的註冊行政區
                if not district or district in ["未知", "無", ""]:
                    district = user.get("district", "全區")

            supply = {
                "id": make_id("S"), "time": now_str(), "source": "平台表單",
                "provider_id": user.get("id"), "provider": provider, "provider_email": user.get("email"),
                "district": district, "village": "全區",
                "location_current": location_current, "lat": lat, "lon": lon,
                "resource_type": resource_type, "category": category, "item": item, "qty": int(qty),
                "has_logistics": "可自行運送" if "✅" in has_logistics else "需車隊協助",
                "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                "verified_by": user.get("id") if user.get("verified") else "", "raw_text": raw_text, "risk_flag": geo_data.get("risk_flag", ""),
            }
            st.session_state.supplies.insert(0, supply)
            st.success(f"✅ 成功！單筆供給已建立。物資來源地『{location_current}』已成功對應至【{district}】。")

    with tab2:
        st.info("企業用戶可直接將 ERP 報表或倉管盤點訊息貼上，AI 將自動拆解為多筆供給庫存。")
        # 💡 加入 key
        bulk_text = st.text_area("📄 貼上庫存盤點清單", height=150, placeholder="範例：林口倉目前有 500箱泡麵，自有車隊可送。烏日倉有 100台發電機，需車隊協助。", help="請盡量保持文意通順，包含地點、品項與數量。", key="bulk_import_text")
        
        # 💡 加入 key 解決崩潰點
        if st.button("🧠 啟動 AI 批次解析", type="primary", key="bulk_parse_btn"):
            if not bulk_text.strip(): 
                st.error("❌ 啟動失敗：請貼上清單內容！")
            else:
                with st.spinner("Llama-3 正在進行語意拆解與推算座標..."):
                    prompt = f"""請從以下文字萃取出物資庫存。請嚴格以 JSON 陣列回傳，不要有 Markdown 標記或其他文字：
                    [ {{"item": "品項", "qty": 數量, "location_current": "存放地", "has_logistics": "可自行運送 或 需車隊協助", "lat": 緯度浮點(若無法判斷填23.5), "lon": 經度浮點(若無法判斷填121.0)}} ]
                    文字：{bulk_text}"""
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
                        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.0)
                        raw_output = res.choices[0].message.content
                        start_idx, end_idx = raw_output.find("["), raw_output.rfind("]")
                        if start_idx != -1 and end_idx != -1:
                            st.session_state.preview_supplies = json.loads(raw_output[start_idx:end_idx+1])
                            st.session_state.bulk_text_cache = bulk_text
                            st.success("✅ 解析成功！請在下方表格確認預覽結果。")
                        else:
                            st.error("❌ 解析失敗：AI 回傳的格式異常，請確認文字內容是否過於複雜。")
                    except Exception as e:
                        st.error(f"❌ 系統錯誤：{str(e)}")

        if st.session_state.preview_supplies:
            st.markdown("### 📝 請確認解析結果 (點擊表格可直接修改)")
            df_preview = pd.DataFrame(st.session_state.preview_supplies)
            
            # 💡 加入 key 確保資料編輯器穩定
            edited_df = st.data_editor(df_preview, num_rows="dynamic", use_container_width=True, key="bulk_data_editor")
            
            # 💡 加入 key
            if st.button("✅ 確認無誤，正式批次入庫", type="primary", key="bulk_confirm_btn"):
                for _, row in edited_df.iterrows():
                    supply = {
                        "id": make_id("S"), "time": now_str(), "source": "ERP批次匯入",
                        "provider_id": user.get("id"), "provider": user.get("name"), "provider_email": user.get("email"),
                        "district": user.get("district", "全區"), "village": "全區",
                        "location_current": row.get("location_current", user.get("district")), 
                        "lat": float(row.get("lat", 23.5)), "lon": float(row.get("lon", 121.0)), 
                        "resource_type": "有形資源", "category": "批次匯入", 
                        "item": row.get("item"), "qty": int(row.get("qty", 1)),
                        "has_logistics": row.get("has_logistics", "需車隊協助"),
                        "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                        "verified_by": user.get("id") if user.get("verified") else "",
                        "raw_text": st.session_state.get("bulk_text_cache", ""), "risk_flag": "",
                    }
                    st.session_state.supplies.insert(0, supply)
                st.session_state.preview_supplies = None
                st.success(f"✅ 成功！已為您批次入庫 {len(edited_df)} 筆物資。")
                time.sleep(1.5)
                st.rerun()


def page_public_claims():
    user = get_current_user()
    st.title("🤝 我要認領需求")
    st.caption("一般民眾、公司/團體都可以認領；但系統會先媒合檢查，再交由政府或管理員審核，通過後才會正式扣庫存。")

    pending_demands = [d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    if not pending_demands:
        st.info("目前沒有可認領需求。")
        return

    only_verified = st.toggle("只顯示已認證需求", value=False)
    selected_type = st.selectbox("篩選資源型態", ["全部"] + list(RESOURCE_TYPES.keys()))
    if only_verified:
        pending_demands = [d for d in pending_demands if d.get("verification_status") == "verified"]
    if selected_type != "全部":
        pending_demands = [d for d in pending_demands if d.get("resource_type") == selected_type]

    my_supplies = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id") and s.get("qty", 0) > 0]

    if not my_supplies:
        st.warning("你目前還沒有可用供給。可以先到「📦 建立供給」新增，或在下方快速建立。")
        with st.expander("快速建立供給"):
            with st.form("quick_supply"):
                provider = st.text_input("提供者名稱", value=user.get("name"))
                resource_type, category = resource_selectors("quick_supply")
                item = st.text_input("可提供品項")
                qty = st.number_input("可提供數量", min_value=1, value=1, key="quick_qty")
                location_current = st.text_input("目前所在地", value=user.get("district"))
                submitted = st.form_submit_button("建立供給")
            if submitted and item:
                supply = {
                    "id": make_id("S"),
                    "time": now_str(),
                    "source": "快速供給",
                    "provider_id": user.get("id"),
                    "provider": provider,
                    "provider_email": user.get("email"),
                    "district": user.get("district"),
                    "village": user.get("village"),
                    "location_current": location_current,
                    "lat": 23.8,
                    "lon": 121.0,
                    "resource_type": resource_type,
                    "category": category,
                    "item": item,
                    "qty": int(qty),
                    "status": "可調派",
                    "verification_status": "verified" if user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("verified") else "",
                    "raw_text": "快速建立供給",
                    "risk_flag": "",
                }
                st.session_state.supplies.insert(0, supply)
                add_audit("快速建立供給", f"{supply['id']} / {item}")
                st.success("已建立供給，請重新進入認領頁面選擇。")
                st.rerun()
        return

    for d in pending_demands:
        with st.container(border=True):
            demand_card(d)
            with st.form(f"claim_form_{d['id']}"):
                supply_id = st.selectbox(
                    "選擇你的供給資源",
                    [s["id"] for s in my_supplies],
                    format_func=lambda sid: next(f"[{s['id']}] {s['item']} x {s['qty']}｜{badge_text(s.get('verification_status'))}" for s in my_supplies if s["id"] == sid),
                    key=f"supply_select_{d['id']}",
                )
                supply = next(s for s in my_supplies if s["id"] == supply_id)
                max_qty = min(int(supply.get("qty", 0)), int(d.get("qty", 0)))
                claim_qty = st.number_input("認領數量", min_value=1, max_value=max_qty, value=max_qty, key=f"claim_qty_{d['id']}")
                note = st.text_area("備註", placeholder="例如：可今天下午送達、需協助搬運等", key=f"claim_note_{d['id']}")
                submitted = st.form_submit_button("送出認領申請")
            if submitted:
                submit_claim(d, supply, int(claim_qty), note)
                st.rerun()


def page_gov_review():
    user = get_current_user()
    st.title("🏛️ 政府審核中心")
    st.caption("政府單位只能審核同一行政區或村里的民眾需求與認領申請。")

    tab1, tab2 = st.tabs(["🚨 需求批次認證", "📋 認領申請審核 (附戰情地圖)"])

    # ==========================================
    # 痛點 1 & 3 解決：緊急度降冪排序與批次審核 (Bulk Action)
    # ==========================================
    with tab1:
        st.subheader("🚨 轄區需求批次認證")
        st.write("請在表格中直接勾選欲核准的項目，或填寫駁回理由，最後點擊下方按鈕批次送出。已依「緊急度」為您降冪排序。")
        
        reviewable_demands = [d for d in st.session_state.demands if d.get("verification_status") == "pending" and can_gov_review(user, d)]
        
        if not reviewable_demands:
            st.info("目前沒有可審核的需求。")
        else:
            # 💡 依照緊急度排序：最高危險的放在最上方
            reviewable_demands = sorted(reviewable_demands, key=lambda x: x.get("urgency", 0), reverse=True)
            
            # 準備轉換為 Pandas DataFrame 的格式
            df_data = []
            for d in reviewable_demands:
                df_data.append({
                    "id": d["id"],
                    "緊急度": "🔴" * d.get("urgency", 3),  # 💡 將數字轉為視覺化的警示燈號
                    "地點": d.get("location", "未知"),
                    "品項": f"{d.get('item')} x {d.get('qty')}",
                    "通報人": d.get("requester_name", "未知"),
                    "通報內容": d.get("raw_text", ""),
                    "核准": False,
                    "駁回": False,
                    "審核備註": ""
                })
                
            df = pd.DataFrame(df_data)
            
            # 💡 導入 st.data_editor 讓政府官員可以批次勾選
            edited_df = st.data_editor(
                df,
                column_config={
                    "核准": st.column_config.CheckboxColumn("✅ 批次核准", default=False),
                    "駁回": st.column_config.CheckboxColumn("❌ 批次駁回", default=False),
                    "審核備註": st.column_config.TextColumn("備註(若駁回強烈建議填寫)"),
                },
                disabled=["id", "緊急度", "地點", "品項", "通報人", "通報內容"], # 鎖定原始資料不可被修改
                hide_index=True,
                use_container_width=True
            )
            
            if st.button("🚀 送出批次審核", type="primary"):
                processed_count = 0
                for index, row in edited_df.iterrows():
                    # 防呆機制：不能同時勾選核准與駁回
                    if row["核准"] and row["駁回"]:
                        st.warning(f"需求 {row['id']} 不能同時勾選核准與駁回，已略過該筆。")
                        continue
                        
                    if row["核准"] or row["駁回"]:
                        d_ref = next((x for x in st.session_state.demands if x["id"] == row["id"]), None)
                        if d_ref:
                            if row["核准"]:
                                d_ref["verification_status"] = "verified"
                                d_ref["verified_by"] = user.get("id")
                                add_audit("政府批次認證需求", f"{d_ref['id']} 通過 / {row['審核備註']}")
                                add_notification(f"✅ 需求已由 {user.get('name')} 認證：{d_ref.get('item')}", "review")
                            elif row["駁回"]:
                                d_ref["verification_status"] = "rejected"
                                d_ref["status"] = "已駁回"
                                d_ref["risk_flag"] = row["審核備註"] or "地方政府駁回"
                                add_audit("政府批次駁回需求", f"{d_ref['id']} / {row['審核備註']}")
                            processed_count += 1
                            
                if processed_count > 0:
                    st.success(f"✅ 已成功批次處理 {processed_count} 筆需求！")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.info("您尚未勾選處理任何項目。")

    # ==========================================
    # 痛點 2 & 4 解決：地圖空間預覽與 AI 決策透明化
    # ==========================================
    with tab2:
        st.subheader("📋 認領申請審核")
        reviewable_claims = []
        for c in st.session_state.claims:
            if c.get("status") != "pending_gov_review":
                continue
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            if d and can_gov_review(user, d):
                reviewable_claims.append(c)

        if not reviewable_claims:
            st.info("目前沒有你可審核的認領申請。")

        # 💡 同樣依照需求緊急度排序
        def get_claim_urgency(c_dict):
            d_temp = next((x for x in st.session_state.demands if x["id"] == c_dict["demand_id"]), {})
            return d_temp.get("urgency", 0)

        reviewable_claims = sorted(reviewable_claims, key=get_claim_urgency, reverse=True)

        for c in reviewable_claims:
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            s = next((x for x in st.session_state.supplies if x["id"] == c["supply_id"]), None)
            if not d or not s:
                continue
                
            urgency_stars = "🔴" * d.get("urgency", 3)

            with st.container(border=True):
                st.markdown(f"### 申請 {c['id']}｜{c['claimant_name']} 認領 {d.get('item')} x {c.get('claim_qty')}")
                st.markdown(f"**緊急度：** {urgency_stars}")
                
                # 💡 佈局拆分：左側文字審核區，右側地圖視覺區
                col_info, col_map = st.columns([1, 1])
                
                with col_info:
                    st.write(f"**🚨 需求方：** {d.get('location')}｜{badge_text(d.get('verification_status'))}")
                    st.write(f"**📦 供給方：** {s.get('provider')} ({s.get('location_current')})｜庫存 {s.get('qty')}｜{badge_text(s.get('verification_status'))}")
                    
                    score = c.get("match_score", 0)
                    if score >= 80:
                        st.progress(score / 100, text=f"🟢 系統媒合分數：{score} (極度吻合)")
                    elif score >= 50:
                        st.progress(score / 100, text=f"🟡 系統媒合分數：{score} (尚可接受)")
                    else:
                        st.progress(score / 100, text=f"🔴 系統媒合分數：{score} (風險較高)")
                    
                    # 💡 展開 AI 的推理邏輯，提供審核上下文
                    with st.expander("🤖 點此查看 AI 決策詳解與風險提示"):
                        st.info(c.get('match_reason', '無詳細理由'))
                        
                    note = st.text_input("審核備註", key=f"gov_c_note_{c['id']}")
                    col_a, col_b = st.columns(2)
                    
                    if col_a.button("✅ 核准認領", key=f"gov_approve_c_{c['id']}", type="primary"):
                        c["reviewer"] = user.get("name")
                        c["review_note"] = note or "地方政府審核通過"
                        ok = execute_dispatch(d["id"], s["id"], s.get("provider"), c.get("claim_qty"), claim_id=c["id"])
                        if ok:
                            st.success("已完成配對。")
                            time.sleep(1)
                        else:
                            st.error("配對失敗，可能是庫存或需求不足。")
                        st.rerun()
                        
                    if col_b.button("❌ 駁回認領", key=f"gov_reject_c_{c['id']}"):
                        c["status"] = "rejected"
                        c["reviewer"] = user.get("name")
                        c["review_note"] = note or "地方政府駁回"
                        c["review_time"] = now_str()
                        notify_claim_result(d, s, c, result="rejected")
                        add_audit("政府駁回認領", f"{c['id']} / {note}")
                        st.rerun()
                        
                with col_map:
                    # 💡 渲染路線預覽地圖，賦予官員空間概念
                    map_data = []
                    if d.get("lat") and d.get("lon"):
                        map_data.append({"lat": float(d["lat"]), "lon": float(d["lon"]), "color": "#FF0000"}) # 需求紅點
                    if s.get("lat") and s.get("lon"):
                        map_data.append({"lat": float(s["lat"]), "lon": float(s["lon"]), "color": "#00FF00"}) # 供給綠點
                        
                    if map_data:
                        st.caption("🗺️ 空間連線預覽 (紅點：災區 / 綠點：物資地)")
                        st.map(pd.DataFrame(map_data), color="color", zoom=6, use_container_width=True)


def page_map_pool():
    st.title("🗺️ 戰備資源池")
    map_data = []
    for d in st.session_state.demands:
        if d.get("lat") and d.get("lon") and d.get("status") not in ["已駁回"]:
            map_data.append({"lat": d["lat"], "lon": d["lon"], "color": "#FF0000"})
    for s in st.session_state.supplies:
        if s.get("lat") and s.get("lon") and s.get("qty", 0) > 0:
            map_data.append({"lat": s["lat"], "lon": s["lon"], "color": "#00AA00"})
    if map_data:
        st.markdown("🔴 需求點 ｜ 🟢 供給點")
        st.map(pd.DataFrame(map_data), color="color", zoom=6, use_container_width=True)

    st.divider()
    tab1, tab2, tab3, tab4 = st.tabs(["需求池", "供給池", "認領申請", "智慧配對建議"])
    with tab1:
        df = pd.DataFrame(st.session_state.demands)
        cols = ["id", "district", "village", "item", "qty", "resource_type", "category", "verification_status", "status", "matched_provider"]
        st.dataframe(df[[c for c in cols if c in df.columns]], hide_index=True, use_container_width=True)
    with tab2:
        df = pd.DataFrame(st.session_state.supplies)
        cols = ["id", "provider", "district", "item", "qty", "resource_type", "category", "verification_status", "status"]
        st.dataframe(df[[c for c in cols if c in df.columns]], hide_index=True, use_container_width=True)
    with tab3:
        df = pd.DataFrame(st.session_state.claims)
        if df.empty:
            st.info("目前尚無認領申請。")
        else:
            st.dataframe(df, hide_index=True, use_container_width=True)
    with tab4:
        df = pd.DataFrame(st.session_state.smart_matches)
        if df.empty:
            st.info("目前尚無智慧配對建議。")
        else:
            st.dataframe(df, hide_index=True, use_container_width=True)


def page_ai_match():
    st.title("🤖 AI 調配引擎")
    pending_demands = [d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    available_supplies = [s for s in st.session_state.supplies if s.get("qty", 0) > 0]
    if not pending_demands or not available_supplies:
        st.info("目前沒有待處理需求或可用供給。")
        return

    selected_demand_id = st.selectbox(
        "選擇需求",
        [d["id"] for d in pending_demands],
        format_func=lambda did: next(f"[{d['id']}] {d.get('location')} - {d.get('item')} x {d.get('qty')}｜{badge_text(d.get('verification_status'))}" for d in pending_demands if d["id"] == did),
    )
    target_demand = next(d for d in pending_demands if d["id"] == selected_demand_id)

    if st.button("⚡ 啟動 AI 媒合", type="primary"):
        with st.spinner("AI 地理與語意媒合中..."):
            results = ai_match_resources(target_demand, available_supplies)
        if not results or ("error" in results[0]):
            st.warning("AI 演算失敗，改用本地規則媒合。")
            local_results = []
            for s in available_supplies:
                passed, score, reason = simple_match_check(target_demand, s, min(target_demand.get("qty"), s.get("qty")))
                if passed:
                    local_results.append({"supply_id": s["id"], "match_score": score, "reason": reason})
            results = sorted(local_results, key=lambda x: x["match_score"], reverse=True)

        if not results:
            st.info("目前沒有適合資源。")
        else:
            for r in results:
                s = next((x for x in available_supplies if x["id"] == r.get("supply_id")), None)
                if not s:
                    continue
                with st.container(border=True):
                    st.markdown(f"### 推薦：{s.get('provider')} / {s.get('item')}")
                    st.progress(min(r.get("match_score", 0), 100) / 100, text=f"契合度：{r.get('match_score')} 分")
                    st.info(r.get("reason"))
                    qty = min(target_demand.get("qty", 0), s.get("qty", 0))
                    if st.button(f"✅ 管理/政府直接批准調度 {qty} 件", key=f"ai_dispatch_{s['id']}"):
                        execute_dispatch(target_demand["id"], s["id"], s.get("provider"), qty)
                        st.rerun()


def page_multimodal():
    st.title("📥 多模態轉譯 Vision ETL")
    st.caption("適用於快速將網頁截圖、手寫紙條照片轉換為標準格式。")
    col_in, col_out = st.columns(2)
    
    with col_in:
        # 💡 加入隱私防護警告
        uploaded_file = st.file_uploader("📸 上傳災情或物資照片", type=["jpg", "jpeg", "png"], help="⚠️ 為保護隱私，請勿上傳包含清晰人臉或傷患之照片。")
        raw_text_input = st.text_area("✍️ 補充文字說明", placeholder="輸入範例：這是花蓮市運來的 50 頂帳篷，可供支援。")
        
        if st.button("🧠 啟動 AI 解析並建檔", type="primary"):
            img_bytes = uploaded_file.getvalue() if uploaded_file else None
            mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
            text_to_send = raw_text_input or "請根據圖片判斷災情與需求，務必找出具體品項與數量。"
            
            with st.spinner("AI 正在進行多模態萃取與 DLP 風險掃描..."):
                result = extract_info_with_ai(text_to_send, img_bytes, mime_type)
                
            with col_out:
                st.subheader("🤖 AI 解析結果")
                st.json(result)
                
            # 💡 熔斷處理
            if result.get("error") == "API_RATE_LIMIT":
                st.warning("⚠️ 目前 API 伺服器滿載，請改用手動表單進行建檔。")
                return
            elif "error" in result:
                st.error(f"❌ 解析失敗：{result['error']}")
                return
                
            extracted = result.get("data", result)
            item = extracted.get("item", "")
            qty = extracted.get("qty", 0)
            risk_flag = extracted.get("risk_flag", "")
            
            if not item or item in ["未知", "無", ""]:
                st.warning("⚠️ 失敗：AI 無法找到『具體物資名稱』。")
                return
            if qty <= 0:
                st.warning("⚠️ 失敗：AI 無法判斷『數量』。")
                return

            user = get_current_user()
            is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
            
            if risk_flag:
                st.warning(f"🛡️ **DLP 防護啟動**：AI 偵測到 {risk_flag}，已自動遮蔽部分敏感細節。")
            
            if is_demand:
                record = {
                    "id": make_id("D"), "time": now_str(), "source": "AI轉譯",
                    "requester_id": user.get("id"), "requester_name": user.get("name"), "requester_email": user.get("email"),
                    "status": "未處理", "matched_provider": "", "verification_status": "verified" if user.get("role") == "government" and user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("role") == "government" and user.get("verified") else "",
                    "raw_text": text_to_send, "risk_flag": "",
                }
                record.update(extracted)
                if not record.get("district") or record.get("district") in ["未知", ""]: record["district"] = user.get("district", "全區")
                if not record.get("village") or record.get("village") in ["未知", ""]: record["village"] = user.get("village", "全區")
                st.session_state.demands.insert(0, record)
                st.success(f"✅ 成功！已寫入一筆需求：{item} x {qty}") # 明確成功回饋
            else:
                record = {
                    "id": make_id("S"), "time": now_str(), "source": "AI轉譯",
                    "provider_id": user.get("id"), "provider": extracted.get("provider") or user.get("name"), "provider_email": user.get("email"),
                    "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("verified") else "", "raw_text": text_to_send, "risk_flag": "",
                }
                record.update(extracted)
                if "location" in record and "location_current" not in record: record["location_current"] = record["location"]
                if not record.get("district") or record.get("district") in ["未知", ""]: record["district"] = user.get("district", "全區")
                if not record.get("village") or record.get("village") in ["未知", ""]: record["village"] = user.get("village", "全區")
                st.session_state.supplies.insert(0, record)
                st.success(f"✅ 成功！已寫入一筆供給：{item} x {qty}") # 明確成功回饋


def page_chatbot():
    user = get_current_user()
    st.title("💬 智慧對話通報 (支援多模態)")
    
    # 💡 痛點 2 解決：宣告弱網 / SMS 簡訊閘道備援機制
    st.info("📡 **弱網備援機制啟動**：若因災區基地台損毀導致連線不穩，請直接發送簡訊『地點+需求』至 `0911-RES-CUE`，邊緣運算節點將自動轉譯並同步至本儀表板。")
    
    # 💡 痛點 4 解決：隱私與道德警告
    uploaded_file = st.file_uploader(
        "📸 附加現場照片 (選填)", 
        type=["jpg", "jpeg", "png"], 
        help="⚠️ 隱私防護提醒：請勿上傳包含清晰人臉、傷亡者遺體或身分證件之照片，系統內建 DLP 將自動攔截並標記高風險檔案。"
    )

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    if user_input := st.chat_input("輸入範例：壽豐鄉中山路淹水，急需 5 台抽水機支援！"):
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("AI 正在解析通報內容..."):
                img_bytes = uploaded_file.getvalue() if uploaded_file else None
                mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
                
                result = extract_info_with_ai(raw_text=user_input, image_bytes=img_bytes, mime_type=mime_type)
                
                # 💡 痛點 3 解決：API 熔斷降級處理
                if result.get("error") == "API_RATE_LIMIT":
                    reply = "⚠️ **系統降級通知**：目前 AI 伺服器因湧入大量通報滿載。已暫時關閉 AI 解析，請點擊左側選單的「📣 填寫需求表單」使用純手動模式送出，確保您的資訊不漏接！"
                    st.warning(reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": reply})
                    return
                elif "error" in result:
                    reply = f"❌ **通報失敗**：系統解析發生錯誤 ({result['error']})，請稍後重試。"
                    st.error(reply)
                    return
                    
                extracted = result.get("data", result)
                item = extracted.get("item", "")
                qty = extracted.get("qty", 0)
                risk_flag = extracted.get("risk_flag", "")
                
                if not item or item in ["未知", "無", ""]:
                    reply = "⚠️ **通報失敗**：無法辨識具體的「物資品項」。請重新輸入，例如：『我需要 5 台抽水機』。"
                elif qty <= 0:
                    reply = "⚠️ **通報失敗**：無法辨識有效的「數量」。請明確告知數量。"
                else:
                    is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
                    district = extracted.get("district", user.get("district", "全區"))
                    
                    if is_demand:
                        # 💡 痛點 1 解決：AI 去重與合併建議
                        dup_demand = check_duplicate_demand(district, item)
                        if dup_demand:
                            reply = f"🚨 **系統提示 (發現相似通報)**：\n我們發現同區域已有一筆相似需求：【{dup_demand['id']} - {dup_demand['item']}】。\n為避免資源重疊，系統已將您的通報列為該案件的**緊急附議**，並調升其緊急層級！"
                            dup_demand["qty"] += qty # 自動累加數量
                            dup_demand["urgency"] = min(5, dup_demand.get("urgency", 3) + 1)
                        else:
                            record = {
                                "id": make_id("D"), "time": now_str(), "source": "對話通報",
                                "requester_id": user.get("id"), "requester_name": user.get("name"), "requester_email": user.get("email"),
                                "status": "未處理", "matched_provider": "", "verification_status": "pending", "verified_by": "", "raw_text": user_input, 
                                "risk_flag": risk_flag, # 寫入 DLP 攔截標記
                            }
                            record.update(extracted)
                            if not record.get("district") or record.get("district") in ["未知", ""]: record["district"] = user.get("district", "全區")
                            if not record.get("village") or record.get("village") in ["未知", ""]: record["village"] = user.get("village", "全區")
                            
                            st.session_state.demands.insert(0, record)
                            reply = f"✅ **立案成功**！已寫入需求池：{record.get('item')} x {record.get('qty')}"
                            
                            if risk_flag:
                                reply += f"\n\n*(🛡️ 系統已遮蔽部分包含隱私或敏感內容的資訊)*"
                    else:
                        # 供給端邏輯保持不變
                        record = {
                            "id": make_id("S"), "time": now_str(), "source": "對話通報",
                            "provider_id": user.get("id"), "provider": extracted.get("provider") or user.get("name"), "provider_email": user.get("email"),
                            "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending", "risk_flag": risk_flag,
                        }
                        record.update(extracted)
                        if "location" in record and "location_current" not in record: record["location_current"] = record["location"]
                        if not record.get("district") or record.get("district") in ["未知", ""]: record["district"] = user.get("district", "全區")
                        if not record.get("village") or record.get("village") in ["未知", ""]: record["village"] = user.get("village", "全區")
                        
                        st.session_state.supplies.insert(0, record)
                        reply = f"✅ **立案成功**！感謝提供：{record.get('item')} x {record.get('qty')}"
                
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})



def page_company_supply_chatbot():
    """公司/團體專用：只能用對話方式新增供給，不允許提出需求。"""
    user = get_current_user()
    st.title("💬 AI 供給登錄")
    st.caption("公司/團體專用。你可以像聊天一樣輸入可提供的物資或服務，系統會自動寫入供給池；此頁不開放提出需求。")

    st.info("""
輸入範例：
- 台南永康倉庫可提供 500 箱礦泉水，自有物流可配送
- 公司目前可捐贈 100 箱泡麵，存放在台中烏日倉，需平台協助媒合車隊
- 我們有 20 位志工可支援物資搬運，地點在花蓮市區
- 高雄倉有 30 台發電機可調派，最快今晚出車

提醒：公司/團體帳號在此只能建立「供給」，若要協助需求，請到「供給與認領中心」認領公開需求。
""")

    if "company_supply_chat" not in st.session_state:
        st.session_state.company_supply_chat = [
            {
                "role": "assistant",
                "content": "您好！請直接描述貴單位可提供的物資、人力或服務，例如：『台南永康倉庫可提供 500 箱礦泉水，自有物流可配送』。"
            }
        ]

    for msg in st.session_state.company_supply_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_input := st.chat_input("輸入範例：台南永康倉庫可提供 500 箱礦泉水，自有物流可配送"):
        st.session_state.company_supply_chat.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            demand_keywords = ["需要", "急需", "需求", "求助", "缺", "救援", "幫我找"]
            supply_keywords = ["提供", "可提供", "捐贈", "供給", "支援", "可支援", "可調派", "庫存", "倉庫", "倉"]

            if any(k in user_input for k in demand_keywords) and not any(k in user_input for k in supply_keywords):
                reply = "⚠️ 公司/團體帳號在此頁只能新增『供給』，不能提出需求。若要協助災區，請輸入可提供的物資、數量與所在地。"
                st.warning(reply)
                st.session_state.company_supply_chat.append({"role": "assistant", "content": reply})
                return

            with st.spinner("AI 正在解析供給內容..."):
                # 明確引導 AI 以 Supply 解析，避免公司輸入被誤判為 Demand。
                result = extract_info_with_ai(raw_text=f"這是一筆公司/團體供給資訊，請以 Supply 解析：{user_input}")

            if result.get("error") == "API_RATE_LIMIT":
                reply = "⚠️ AI 目前忙碌，請改用『供給與認領中心 → 建立供給』手動建立。"
                st.warning(reply)
                st.session_state.company_supply_chat.append({"role": "assistant", "content": reply})
                return
            elif "error" in result:
                reply = f"❌ 供給解析失敗：{result.get('error')}"
                st.error(reply)
                st.session_state.company_supply_chat.append({"role": "assistant", "content": reply})
                return

            extracted = result.get("data", result)
            item = extracted.get("item", "")
            qty = normalize_qty(extracted.get("qty", 0), default=0)
            risk_flag = extracted.get("risk_flag", "")

            if not item or item in ["未知", "無", ""]:
                reply = "⚠️ 無法辨識具體供給品項。請重新輸入，例如：『可提供 500 箱礦泉水，存放於台南永康倉』。"
            elif qty <= 0:
                reply = "⚠️ 無法辨識有效數量。請明確告知數量，例如：500 箱、30 台、20 位志工。"
            else:
                record = {
                    "id": make_id("S"),
                    "time": now_str(),
                    "source": "公司AI供給登錄",
                    "provider_id": user.get("id"),
                    "provider": extracted.get("provider") or user.get("name"),
                    "provider_email": user.get("email"),
                    "district": extracted.get("district", user.get("district", "全區")),
                    "village": extracted.get("village", user.get("village", "全區")),
                    "location_current": extracted.get("location_current") or extracted.get("location") or user.get("district"),
                    "lat": extracted.get("lat", 23.8),
                    "lon": extracted.get("lon", 121.0),
                    "resource_type": extracted.get("resource_type", "有形資源"),
                    "category": extracted.get("category", "其他"),
                    "item": item,
                    "qty": qty,
                    "has_logistics": extracted.get("has_logistics", "未註明"),
                    "status": "可調派",
                    "verification_status": "verified" if user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("verified") else "",
                    "raw_text": user_input,
                    "risk_flag": risk_flag,
                }
                st.session_state.supplies.insert(0, record)
                add_audit("公司AI新增供給", f"{record['id']} / {item} x {qty}")
                add_notification(f"🏢 公司新增供給：{item} x {qty}", "supply")
                reply = f"✅ 已成功建立供給：**{item} x {qty}**，編號 `{record['id']}`。你可以到『供給與認領中心 → 我提供的供給』查看。"
                if risk_flag:
                    reply += "\n\n🛡️ 系統已標記此筆資料含敏感資訊，建議後續人工確認。"

            st.markdown(reply)
            st.session_state.company_supply_chat.append({"role": "assistant", "content": reply})


def page_company_supply_claim_center():
    st.title("📦 供給與認領中心")
    st.caption("整合公司/團體最常用的供給建立、供給管理、需求認領與申請追蹤。")
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "AI 供給登錄",
        "建立供給",
        "我提供的供給",
        "我要認領需求",
        "我的認領申請",
    ])
    with tab1:
        page_company_supply_chatbot()
    with tab2:
        page_submit_supply()
    with tab3:
        page_my_supplies()
    with tab4:
        page_public_claims()
    with tab5:
        page_my_claims()


def page_company_logistics_esg_center():
    st.title("🚚 配對物流與 ESG")
    st.caption("整合已配對訂單、物流狀態、企業 ESG 影響力與通知紀錄。")
    tab1, tab2, tab3 = st.tabs(["已配對訂單", "企業 ESG 影響力", "通知紀錄"])
    with tab1:
        page_matched_orders()
    with tab2:
        page_esg_dashboard()
    with tab3:
        if st.session_state.notifications:
            st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
        else:
            st.info("目前沒有通知紀錄。")

def page_smart_match_review():
    user = get_current_user()
    if user.get("role") != "admin":
        st.error("此頁面僅限平台管理員使用。")
        return

    st.title("🧠 智慧配對審核")
    st.caption("系統會自動掃描需求池與供給池，若品項、分類、數量與地區條件符合，就產生配對建議；管理員核准後才會正式扣庫存、建立配對紀錄並通知雙方。")

    with st.container(border=True):
        st.subheader("產生智慧配對建議")
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        with col1:
            min_score = st.slider("最低媒合分數", 30, 100, 45, 5)
        with col2:
            only_verified_demand = st.checkbox("只掃描已認證需求", value=False)
        with col3:
            only_verified_supply = st.checkbox("只掃描已認證供給", value=False)
        with col4:
            st.write("")
            st.write("")
            if st.button("⚡ 自動掃描並產生建議", type="primary", use_container_width=True):
                created = generate_smart_match_suggestions(min_score, only_verified_demand, only_verified_supply)
                if created:
                    st.success(f"已新增 {created} 筆智慧配對建議。")
                else:
                    st.info("目前沒有新的可配對組合，或已存在待審建議。")
                st.rerun()

    st.divider()

    tab1, tab2, tab3 = st.tabs(["待審智慧配對", "已核准", "已駁回/失效"])

    def render_match_card(m):
        d = next((x for x in st.session_state.demands if x.get("id") == m.get("demand_id")), None)
        s = next((x for x in st.session_state.supplies if x.get("id") == m.get("supply_id")), None)

        if not d or not s:
            st.warning(f"{m.get('id')}：需求或供給資料已不存在。")
            return

        st.markdown(f"### [{m.get('id')}] {d.get('item')} x {m.get('suggested_qty')} ｜ {SMART_MATCH_STATUS.get(m.get('status'), m.get('status'))}")
        col_d, col_s = st.columns(2)
        with col_d:
            st.markdown("#### 🚨 需求端")
            st.write(f"地點：{d.get('location')}")
            st.write(f"需求：{d.get('item')}｜剩餘 {d.get('qty')}")
            st.write(f"分類：{d.get('resource_type')} / {d.get('category')}")
            st.write(f"認證：{badge_text(d.get('verification_status'))}")
            st.caption(f"提出者：{d.get('requester_name')}｜緊急度：{d.get('urgency')}")
        with col_s:
            st.markdown("#### 📦 供給端")
            st.write(f"提供者：{s.get('provider')}")
            st.write(f"供給：{s.get('item')}｜庫存 {s.get('qty')}")
            st.write(f"分類：{s.get('resource_type')} / {s.get('category')}")
            st.write(f"認證：{badge_text(s.get('verification_status'))}")
            st.caption(f"所在地：{s.get('location_current')}")

        st.progress(min(int(m.get("match_score", 0)), 100) / 100, text=f"媒合分數：{m.get('match_score')}｜{m.get('match_reason')}")
        if m.get("review_note"):
            st.caption(f"審核備註：{m.get('review_note')}")

    with tab1:
        rows = [m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]
        if not rows:
            st.info("目前沒有待審智慧配對建議。")
        for idx, m in enumerate(rows):
            unique_key = f"{m.get('id')}_{m.get('demand_id')}_{m.get('supply_id')}_{idx}"
            with st.container(border=True):
                render_match_card(m)
                note = st.text_input("管理員審核備註", key=f"smart_note_{unique_key}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ 核准智慧配對並正式調度", key=f"smart_ok_{unique_key}"):
                    ok, msg = approve_smart_match(m.get("id"), note)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
                    st.rerun()
                if col_b.button("❌ 駁回智慧配對", key=f"smart_no_{unique_key}"):
                    reject_smart_match(m.get("id"), note)
                    st.warning("已駁回。")
                    st.rerun()

    with tab2:
        rows = [m for m in st.session_state.smart_matches if m.get("status") == "approved"]
        if not rows:
            st.info("目前沒有已核准的智慧配對。")
        for m in rows:
            with st.container(border=True):
                render_match_card(m)

    with tab3:
        rows = [m for m in st.session_state.smart_matches if m.get("status") in ["rejected", "expired"]]
        if not rows:
            st.info("目前沒有已駁回或失效的智慧配對。")
        for m in rows:
            with st.container(border=True):
                render_match_card(m)


def page_admin():
    user = get_current_user()
    if user.get("role") != "admin":
        st.error("此頁面僅限平台管理員使用。")
        return

    st.title("🛡️ 平台管理員總控台")
    st.caption("管理員功能已集中在本總控台：帳號審核、資料修正、智慧配對、認領審核、通知紀錄與稽核紀錄。")

    tabs = st.tabs(["帳號審核", "需求/供給控管", "智慧配對審核", "認領總審核", "通知與信件", "稽核紀錄"])

    with tabs[0]:
        st.subheader("帳號審核")
        pending_users = [u for u in st.session_state.users if u.get("status") == "pending"]
        if not pending_users:
            st.info("目前沒有待審帳號。")
        for u in pending_users:
            with st.container(border=True):
                st.markdown(f"### {u.get('name')}｜{ROLE_LABELS.get(u.get('role'))}")
                st.write(f"Email：{u.get('email')}｜手機：{u.get('phone', '未填')}（{'已驗證' if u.get('phone_verified') else '未驗證'}）｜行政區：{u.get('district')} / {u.get('village')}")
                st.caption(f"證明資料：{u.get('proof')}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ 核准帳號並給予認證", key=f"admin_user_ok_{u['id']}"):
                    u["status"] = "active"
                    u["verified"] = True
                    add_audit("管理員核准帳號", u.get("name"))
                    st.rerun()
                if col_b.button("❌ 駁回帳號", key=f"admin_user_no_{u['id']}"):
                    u["status"] = "rejected"
                    u["verified"] = False
                    add_audit("管理員駁回帳號", u.get("name"))
                    st.rerun()
        st.divider()
        st.subheader("全部帳號")
        st.dataframe(pd.DataFrame(st.session_state.users), hide_index=True, use_container_width=True)

    with tabs[1]:
        st.subheader("需求/供給控管")
        data_type = st.radio("選擇資料類型", ["需求", "供給"], horizontal=True)
        records = st.session_state.demands if data_type == "需求" else st.session_state.supplies
        if not records:
            st.info("沒有資料。")
        for r in records:
            with st.container(border=True):
                title_item = r.get("item", "未知")
                st.markdown(f"### [{r.get('id')}] {title_item} x {r.get('qty')}｜{badge_text(r.get('verification_status'))}")
                st.write(f"分類：{r.get('resource_type')} / {r.get('category')}｜狀態：{r.get('status')}｜地區：{r.get('district')} / {r.get('village')}")
                if r.get("risk_flag"):
                    st.warning(f"異常標記：{r.get('risk_flag')}")
                col1, col2, col3, col4 = st.columns(4)
                if col1.button("✅ 設為已認證", key=f"admin_verify_{data_type}_{r['id']}"):
                    r["verification_status"] = "verified"
                    r["verified_by"] = user.get("id")
                    add_audit("管理員認證資料", f"{data_type} {r['id']}")
                    st.rerun()
                if col2.button("🟡 設為待認證", key=f"admin_pending_{data_type}_{r['id']}"):
                    r["verification_status"] = "pending"
                    add_audit("管理員重設待認證", f"{data_type} {r['id']}")
                    st.rerun()
                if col3.button("⚠️ 標記異常", key=f"admin_flag_{data_type}_{r['id']}"):
                    r["risk_flag"] = "管理員標記：疑似重複、資訊不足或需人工確認"
                    add_audit("管理員標記異常", f"{data_type} {r['id']}")
                    st.rerun()
                if col4.button("🗑️ 下架資料", key=f"admin_delete_{data_type}_{r['id']}"):
                    r["status"] = "已下架"
                    r["risk_flag"] = "管理員下架"
                    add_audit("管理員下架資料", f"{data_type} {r['id']}")
                    st.rerun()

    with tabs[2]:
        st.subheader("智慧配對審核")
        st.caption("在這裡直接產生、查看、核准或駁回智慧配對建議。管理員核准後才會正式扣庫存、建立配對紀錄並通知雙方。")

        with st.container(border=True):
            st.markdown("#### ⚡ 自動掃描供需並產生建議")
            col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
            with col1:
                min_score = st.slider("最低媒合分數", 30, 100, 45, 5, key="admin_tab_smart_min_score")
            with col2:
                only_verified_demand = st.checkbox("只掃描已認證需求", value=False, key="admin_tab_only_verified_demand")
            with col3:
                only_verified_supply = st.checkbox("只掃描已認證供給", value=False, key="admin_tab_only_verified_supply")
            with col4:
                st.write("")
                st.write("")
                if st.button("⚡ 自動掃描", type="primary", use_container_width=True, key="admin_tab_generate_smart"):
                    created = generate_smart_match_suggestions(min_score, only_verified_demand, only_verified_supply)
                    if created:
                        st.success(f"已新增 {created} 筆智慧配對建議。")
                    else:
                        st.info("目前沒有新的可配對組合，或已存在待審建議。")
                    st.rerun()

        st.divider()
        subtab1, subtab2, subtab3 = st.tabs(["待審智慧配對", "已核准", "已駁回/失效"])

        def render_admin_smart_match(m, idx, readonly=False):
            d = next((x for x in st.session_state.demands if x.get("id") == m.get("demand_id")), None)
            s = next((x for x in st.session_state.supplies if x.get("id") == m.get("supply_id")), None)
            unique_key = f"admin_inline_smart_{m.get('id')}_{m.get('demand_id')}_{m.get('supply_id')}_{idx}"

            if not d or not s:
                st.warning(f"{m.get('id')}：需求或供給資料已不存在。")
                return

            with st.container(border=True):
                st.markdown(f"### [{m.get('id')}] {d.get('item')} x {m.get('suggested_qty')}｜{SMART_MATCH_STATUS.get(m.get('status'), m.get('status'))}")
                col_d, col_s = st.columns(2)
                with col_d:
                    st.markdown("#### 🚨 需求端")
                    st.write(f"地點：{d.get('location')}")
                    st.write(f"需求：{d.get('item')}｜剩餘 {d.get('qty')}")
                    st.write(f"分類：{d.get('resource_type')} / {d.get('category')}")
                    st.write(f"認證：{badge_text(d.get('verification_status'))}")
                    st.caption(f"提出者：{d.get('requester_name')}｜緊急度：{d.get('urgency')}")
                with col_s:
                    st.markdown("#### 📦 供給端")
                    st.write(f"提供者：{s.get('provider')}")
                    st.write(f"供給：{s.get('item')}｜庫存 {s.get('qty')}")
                    st.write(f"分類：{s.get('resource_type')} / {s.get('category')}")
                    st.write(f"認證：{badge_text(s.get('verification_status'))}")
                    st.caption(f"所在地：{s.get('location_current')}")

                st.progress(min(int(m.get("match_score", 0)), 100) / 100, text=f"媒合分數：{m.get('match_score')}｜{m.get('match_reason')}")
                if m.get("review_note"):
                    st.caption(f"審核備註：{m.get('review_note')}")

                if not readonly:
                    note = st.text_input("管理員審核備註", key=f"{unique_key}_note")
                    col_a, col_b = st.columns(2)
                    if col_a.button("✅ 核准智慧配對並正式調度", key=f"{unique_key}_ok"):
                        ok, msg = approve_smart_match(m.get("id"), note)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()
                    if col_b.button("❌ 駁回智慧配對", key=f"{unique_key}_no"):
                        reject_smart_match(m.get("id"), note)
                        st.warning("已駁回。")
                        st.rerun()

        with subtab1:
            rows = [m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]
            if not rows:
                st.info("目前沒有待審智慧配對。請按上方『自動掃描』產生建議。")
            for idx, m in enumerate(rows):
                render_admin_smart_match(m, idx, readonly=False)

        with subtab2:
            rows = [m for m in st.session_state.smart_matches if m.get("status") == "approved"]
            if not rows:
                st.info("目前沒有已核准的智慧配對。")
            for idx, m in enumerate(rows):
                render_admin_smart_match(m, idx, readonly=True)

        with subtab3:
            rows = [m for m in st.session_state.smart_matches if m.get("status") in ["rejected", "expired"]]
            if not rows:
                st.info("目前沒有已駁回或失效的智慧配對。")
            for idx, m in enumerate(rows):
                render_admin_smart_match(m, idx, readonly=True)

    with tabs[3]:
        st.subheader("認領總審核")
        pending_claims = [c for c in st.session_state.claims if c.get("status") == "pending_gov_review"]
        if not pending_claims:
            st.info("目前沒有待審認領申請。")
        for c in pending_claims:
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            s = next((x for x in st.session_state.supplies if x["id"] == c["supply_id"]), None)
            if not d or not s:
                continue
            with st.container(border=True):
                st.markdown(f"### {c['id']}｜{c['claimant_name']} 認領 {d.get('item')} x {c.get('claim_qty')}")
                st.write(f"需求：{d.get('location')}｜{badge_text(d.get('verification_status'))}")
                st.write(f"供給：{s.get('provider')} / {s.get('item')}｜庫存 {s.get('qty')}｜{badge_text(s.get('verification_status'))}")
                st.progress(min(c.get("match_score", 0), 100) / 100, text=f"媒合分數：{c.get('match_score')}｜{c.get('match_reason')}")
                note = st.text_input("管理員審核備註", key=f"admin_claim_note_{c['id']}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ 管理員核准並完成配對", key=f"admin_claim_ok_{c['id']}"):
                    c["reviewer"] = user.get("name")
                    c["review_note"] = note or "管理員審核通過"
                    execute_dispatch(d["id"], s["id"], s.get("provider"), c.get("claim_qty"), claim_id=c["id"])
                    st.rerun()
                if col_b.button("❌ 管理員駁回", key=f"admin_claim_no_{c['id']}"):
                    c["status"] = "rejected"
                    c["reviewer"] = user.get("name")
                    c["review_note"] = note or "管理員駁回"
                    c["review_time"] = now_str()
                    notify_claim_result(d, s, c, result="rejected")
                    add_audit("管理員駁回認領", c["id"])
                    st.rerun()

    with tabs[4]:
        st.subheader("通知與 Email 紀錄")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 通知紀錄")
            st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
        with col2:
            st.markdown("#### Email 紀錄")
            st.dataframe(pd.DataFrame(st.session_state.email_logs), hide_index=True, use_container_width=True)

    with tabs[5]:
        st.subheader("稽核紀錄")
        if st.session_state.audit_logs:
            st.dataframe(pd.DataFrame(st.session_state.audit_logs), hide_index=True, use_container_width=True)
        else:
            st.info("目前無稽核紀錄。")



# =========================================================
# 6.5 依架構圖補齊的角色儀表板與分頁
# =========================================================
def page_role_dashboard():
    user = get_current_user()
    role = user.get("role")
    st.title(f"📊 {ROLE_LABELS.get(role)}儀表板")

    my_demands = [d for d in st.session_state.demands if d.get("requester_id") == user.get("id")]
    my_supplies = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id")]
    my_claims = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id")]

    if role == "government":
        area_demands = [d for d in st.session_state.demands if can_gov_review(user, d)]
        area_claims = []
        for c in st.session_state.claims:
            d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), None)
            if d and can_gov_review(user, d):
                area_claims.append(c)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("轄區需求", len(area_demands))
        col2.metric("待認證需求", len([d for d in area_demands if d.get("verification_status") == "pending"]))
        col3.metric("待審認領", len([c for c in area_claims if c.get("status") == "pending_gov_review"]))
        col4.metric("已完成配對", len([d for d in area_demands if d.get("status") == "已完成配對"]))
        st.info("你可以在『需求審核』認證同區/同里的民眾需求，在『供給審核』確認供給方資料，在『認領申請審核』核准媒合。")

    elif role == "company":
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("我的供給", len(my_supplies))
        col2.metric("可調派庫存", sum(int(s.get("qty", 0)) for s in my_supplies))
        col3.metric("我的認領申請", len(my_claims))
        col4.metric("已核准配對", len([c for c in my_claims if c.get("status") == "approved"]))
        st.info("你可以先建立供給，再到『我要認領需求』挑選已公開需求。認領會先做系統媒合檢查，通過後才送政府或管理員審核。")

    elif role == "citizen":
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("我的需求", len(my_demands))
        col2.metric("待認證需求", len([d for d in my_demands if d.get("verification_status") == "pending"]))
        col3.metric("我的認領申請", len(my_claims))
        col4.metric("通知數", len(st.session_state.notifications))
        st.info("一般民眾可以提出需求，也可以建立小量供給並認領需求；但認領不會直接成立，需通過媒合檢查與審核。")

    elif role == "admin":
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("全平台需求", len(st.session_state.demands))
        col2.metric("全平台供給", len(st.session_state.supplies))
        col3.metric("待審帳號", len([u for u in st.session_state.users if u.get("status") == "pending"]))
        col4.metric("待審認領", len([c for c in st.session_state.claims if c.get("status") == "pending_gov_review"]))
        st.metric("待審智慧配對", len([m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]))
        st.info("管理員負責平台總控：帳號審核、需求/供給下架、異常標記、智慧配對審核、認領總審核、通知與稽核紀錄。")

def page_gov_inbox():
    user = get_current_user()
    st.title(f"📥 {user.get('district')} - 戰情收件匣")
    st.caption("AI 已經為您完成初步分流與風險評估，請專注於高優先級的任務。")

    pending_demands = [d for d in st.session_state.demands if d.get("verification_status") == "pending" and can_gov_review(user, d)]
    
    reviewable_claims = []
    for c in st.session_state.claims:
        if c.get("status") == "pending_gov_review":
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            if d and can_gov_review(user, d):
                reviewable_claims.append(c)

    # 💡 AI 分流邏輯 (Triage)
    green_demands = [d for d in pending_demands if d.get("urgency", 0) >= 3 and len(d.get("raw_text", "")) > 5]
    red_demands = [d for d in pending_demands if "現金" in d.get("item", "") or "錢" in d.get("item", "") or d.get("qty", 1) > 1000]
    
    st.subheader("🚨 智能警報 (Smart Alerts)")
    if red_demands:
        st.error(f"⚠️ **高風險警告**：偵測到 {len(red_demands)} 筆疑似惡意或資源異常通報，請優先人工介入防堵！")
    elif pending_demands or reviewable_claims:
        st.warning(f"💡 **AI 建議**：有 {len(green_demands)} 筆需求經 AI 判斷為【綠燈 (合理且緊急)】，建議可至對話助理進行一鍵核准。")
    else:
        st.success("🎉 目前轄區一切平靜，無待辦事項。")

    st.divider()
    st.subheader("📋 待辦任務清單 (To-Do List)")
    
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.metric("待認證：民眾災情需求", f"{len(pending_demands)} 筆")
            if st.button("前往 AI 助理快速處理 ➡️", key="btn_go_chat", use_container_width=True):
                st.info("請點擊左側選單的「🤖 AI 指揮官助理」下達指令。")
    with col2:
        with st.container(border=True):
            st.metric("待核准：資源調度與認領", f"{len(reviewable_claims)} 筆")
            if st.button("前往人工審核中心 ➡️", key="btn_go_review", use_container_width=True):
                st.info("請點擊左側選單的「✅ 需求與認領審核」進行細部確認。")
                
def page_gov_chatbot():
    user = get_current_user()
    st.title("🤖 AI 指揮官助理")
    st.caption("可用自然語言完成：批次核准、資源搜尋、災情總結、提出需求、建立供給。")

    st.info("""
輸入範例：
- 幫我處理今日需求
- 尋找附近可用的抽水機
- 總結目前的災情狀況
- 新增需求：花蓮縣壽豐鄉中山路淹水，急需 5 台抽水機，緊急度 5
- 新增供給：花蓮市區有 3 台抽水機可支援，提供者是吉普車救援隊
""")

    if "gov_chat" not in st.session_state:
        st.session_state.gov_chat = [
            {
                "role": "assistant",
                "content": """長官您好！我是您的 AI 戰情助理。

您可以直接輸入：
- 「新增需求：地點 + 物資 + 數量」
- 「新增供給：地點 + 物資 + 數量」
- 「幫我處理今日需求」
- 「尋找附近可用的抽水機」
- 「總結目前的災情狀況」
""",
            }
        ]

    for msg in st.session_state.gov_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_input := st.chat_input("範例：新增需求：壽豐鄉中山路淹水，急需 5 台抽水機"):
        st.session_state.gov_chat.append({"role": "user", "content": user_input})

        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            # 1. 政府 AI 助理：新增需求
            if "新增需求" in user_input or "提出需求" in user_input or "建立需求" in user_input:
                with st.spinner("AI 正在解析需求內容..."):
                    result = extract_info_with_ai(raw_text=user_input)

                if result.get("error") == "API_RATE_LIMIT":
                    reply = "⚠️ AI 目前忙碌，請改用『個人設定與表單 → 填寫需求表單』手動建立。"
                elif "error" in result:
                    reply = f"❌ 需求解析失敗：{result.get('error')}"
                else:
                    extracted = result.get("data", result)
                    item = extracted.get("item", "")
                    qty = int(extracted.get("qty", 0) or 0)

                    if not item or item in ["未知", "無", ""] or qty <= 0:
                        reply = "⚠️ 無法辨識需求品項或數量，請輸入：新增需求：地點、品項、數量、緊急度。"
                    else:
                        record = {
                            "id": make_id("D"),
                            "time": now_str(),
                            "source": "政府AI指揮官助理",
                            "requester_id": user.get("id"),
                            "requester_name": user.get("name"),
                            "requester_email": user.get("email"),
                            "district": extracted.get("district", user.get("district", "全區")),
                            "village": extracted.get("village", user.get("village", "全區")),
                            "location": extracted.get("location", user_input),
                            "lat": extracted.get("lat", 23.8),
                            "lon": extracted.get("lon", 121.0),
                            "resource_type": extracted.get("resource_type", "有形資源"),
                            "category": extracted.get("category", "其他"),
                            "item": item,
                            "qty": qty,
                            "urgency": int(extracted.get("urgency", 4) or 4),
                            "status": "未處理",
                            "matched_provider": "",
                            "verification_status": "verified",
                            "verified_by": user.get("id"),
                            "raw_text": user_input,
                            "risk_flag": extracted.get("risk_flag", ""),
                        }
                        st.session_state.demands.insert(0, record)
                        add_audit("政府AI新增需求", f"{record['id']} / {item} x {qty}")
                        add_notification(f"🏛️ 政府新增需求：{item} x {qty}", "government_demand")
                        reply = f"✅ 已由政府 AI 指揮官助理建立需求：**{item} x {qty}**，編號 `{record['id']}`。"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 2. 政府 AI 助理：新增供給
            elif "新增供給" in user_input or "提供供給" in user_input or "建立供給" in user_input:
                with st.spinner("AI 正在解析供給內容..."):
                    result = extract_info_with_ai(raw_text=user_input)

                if result.get("error") == "API_RATE_LIMIT":
                    reply = "⚠️ AI 目前忙碌，請改用『個人設定與表單 → 填寫供給表單』手動建立。"
                elif "error" in result:
                    reply = f"❌ 供給解析失敗：{result.get('error')}"
                else:
                    extracted = result.get("data", result)
                    item = extracted.get("item", "")
                    qty = int(extracted.get("qty", 0) or 0)

                    if not item or item in ["未知", "無", ""] or qty <= 0:
                        reply = "⚠️ 無法辨識供給品項或數量，請輸入：新增供給：地點、品項、數量、提供者。"
                    else:
                        record = {
                            "id": make_id("S"),
                            "time": now_str(),
                            "source": "政府AI指揮官助理",
                            "provider_id": user.get("id"),
                            "provider": extracted.get("provider") or user.get("name"),
                            "provider_email": user.get("email"),
                            "district": extracted.get("district", user.get("district", "全區")),
                            "village": extracted.get("village", user.get("village", "全區")),
                            "location_current": extracted.get("location_current") or extracted.get("location") or user.get("district"),
                            "lat": extracted.get("lat", 23.8),
                            "lon": extracted.get("lon", 121.0),
                            "resource_type": extracted.get("resource_type", "有形資源"),
                            "category": extracted.get("category", "其他"),
                            "item": item,
                            "qty": qty,
                            "status": "可調派",
                            "verification_status": "verified",
                            "verified_by": user.get("id"),
                            "raw_text": user_input,
                            "risk_flag": extracted.get("risk_flag", ""),
                        }
                        st.session_state.supplies.insert(0, record)
                        add_audit("政府AI新增供給", f"{record['id']} / {item} x {qty}")
                        add_notification(f"🏛️ 政府新增供給：{item} x {qty}", "government_supply")
                        reply = f"✅ 已由政府 AI 指揮官助理建立供給：**{item} x {qty}**，編號 `{record['id']}`。"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 3. 原本功能：處理需求
            elif "需求" in user_input and ("處理" in user_input or "核准" in user_input or "列出" in user_input):
                pending = [
                    d for d in st.session_state.demands
                    if d.get("verification_status") == "pending" and can_gov_review(user, d)
                ]

                if not pending:
                    reply = "報告長官，目前轄區內沒有待審核的需求。"
                else:
                    reply = f"報告長官，目前轄區有 **{len(pending)}** 筆待審核需求。是否需要我為您一鍵批次核准？"
                    st.session_state.awaiting_action = "approve_all_demands"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 4. 原本功能：尋找資源
            elif "抽水機" in user_input or "尋找" in user_input or "搜尋" in user_input:
                keyword = "抽水機" if "抽水機" in user_input else ""
                available = [
                    s for s in st.session_state.supplies
                    if int(s.get("qty", 0)) > 0
                    and s.get("status") not in ["已駁回", "已下架", "已指派 (無庫存)"]
                    and (not keyword or keyword in str(s.get("item", "")))
                ]

                if available:
                    s = available[0]
                    reply = f"""報告長官，找到可用資源：

- **來源**：{s.get('provider')}
- **品項**：{s.get('item')}
- **庫存**：{s.get('qty')}
- **位置**：{s.get('location_current')}
- **狀態**：{s.get('status')}
"""
                else:
                    reply = "報告長官，目前供給池沒有找到符合條件的可用資源。"

                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            # 5. 災情總結
            elif "總結" in user_input or "狀況" in user_input or "摘要" in user_input:
                area_demands = [d for d in st.session_state.demands if can_gov_review(user, d)]
                area_supplies = [s for s in st.session_state.supplies if can_gov_review(user, s)]

                high_urgency = [d for d in area_demands if int(d.get("urgency", 0) or 0) >= 4]
                pending_review = [d for d in area_demands if d.get("verification_status") == "pending"]
                unhandled = [d for d in area_demands if d.get("status") == "未處理"]

                reply = f"""目前轄區戰情摘要：

- 需求總數：**{len(area_demands)}** 筆
- 供給總數：**{len(area_supplies)}** 筆
- 高緊急需求：**{len(high_urgency)}** 筆
- 待認證需求：**{len(pending_review)}** 筆
- 未處理需求：**{len(unhandled)}** 筆

建議優先處理高緊急度、已具體描述地點與數量的需求。
"""
                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

            else:
                reply = "收到指令。您可以輸入：新增需求、新增供給、處理今日需求、尋找資源，或總結目前災情。"
                st.markdown(reply)
                st.session_state.gov_chat.append({"role": "assistant", "content": reply})

    if st.session_state.get("awaiting_action") == "approve_all_demands":
        if st.button("🚀 確認授權：一鍵核准所有安全需求", type="primary"):
            pending = [
                d for d in st.session_state.demands
                if d.get("verification_status") == "pending" and can_gov_review(user, d)
            ]
            for d in pending:
                d["verification_status"] = "verified"
                d["verified_by"] = user["id"]

            st.session_state.awaiting_action = None
            st.success(f"✅ 已核准 {len(pending)} 筆需求。")
            st.session_state.gov_chat.append({
                "role": "assistant",
                "content": f"✅ 已為您成功核准 {len(pending)} 筆需求。",
            })
            time.sleep(1)
            st.rerun()

def page_my_demands():
    user = get_current_user()
    st.title("📌 我的需求")
    rows = [d for d in st.session_state.demands if d.get("requester_id") == user.get("id")]
    if not rows:
        st.info("你目前尚未提出需求。")
        return
    for d in rows:
        with st.container(border=True):
            demand_card(d)
            st.caption(f"原始說明：{d.get('raw_text', '')}")


def page_my_supplies():
    user = get_current_user()
    st.title("📦 我提供的供給")
    rows = [s for s in st.session_state.supplies if s.get("provider_id") == user.get("id")]
    if not rows:
        st.info("你目前尚未建立供給。")
        return
    for s in rows:
        with st.container(border=True):
            st.markdown(f"### {badge_text(s.get('verification_status'))} [{s.get('id')}] {s.get('item')} x {s.get('qty')}")
            st.write(f"📍 {s.get('location_current')}｜分類：{s.get('resource_type')} / {s.get('category')}｜狀態：{s.get('status')}")
            st.caption(f"提供者：{s.get('provider')}｜說明：{s.get('raw_text', '')}")
            if s.get("risk_flag"):
                st.warning(f"異常標記：{s.get('risk_flag')}")


def page_my_claims():
    user = get_current_user()
    st.title("📋 我的認領申請")
    rows = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id")]
    if not rows:
        st.info("你目前沒有認領申請。")
        return
    for c in rows:
        d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), None)
        s = next((x for x in st.session_state.supplies if x.get("id") == c.get("supply_id")), None)
        with st.container(border=True):
            st.markdown(f"### [{c.get('id')}] {CLAIM_STATUS.get(c.get('status'), c.get('status'))}")
            st.write(f"需求：{d.get('location') if d else '已不存在'}｜{d.get('item') if d else ''} x {c.get('claim_qty')}")
            st.write(f"供給：{s.get('provider') if s else '已不存在'}｜{s.get('item') if s else ''}")
            st.progress(min(int(c.get('match_score', 0)), 100) / 100, text=f"媒合分數：{c.get('match_score')}｜{c.get('match_reason')}")
            if c.get("review_note"):
                st.caption(f"審核備註：{c.get('review_note')}")


def page_matched_orders():
    user = get_current_user()
    st.title("🚚 已配對訂單 / 配送進度")
    related = []
    
    for c in st.session_state.claims:
        if c.get("status") != "approved":
            continue
        d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), None)
        s = next((x for x in st.session_state.supplies if x.get("id") == c.get("supply_id")), None)
        if not d or not s:
            continue
        if user.get("role") in ["admin", "government"] or c.get("claimant_id") == user.get("id") or d.get("requester_id") == user.get("id"):
            related.append((c, d, s))
            
    if not related:
        st.info("目前沒有已核准的配對訂單。")
        return
        
    for c, d, s in related:
        # 💡 初始化訂單的物流狀態
        if "fulfillment_status" not in c:
            c["fulfillment_status"] = "待出貨"
            
        with st.container(border=True):
            st.markdown(f"### ✅ 訂單 {c.get('id')}｜{s.get('provider')} ➡️ {d.get('location')}")
            
            col_info, col_action = st.columns([2, 1])
            with col_info:
                st.write(f"📦 物資：**{d.get('item')} x {c.get('claim_qty')}**")
                st.write(f"🚚 模式：{s.get('has_logistics', '可自行運送')}")
                
                # 依據狀態顯示不同顏色
                status_color = "red" if c["fulfillment_status"] == "待出貨" else ("orange" if c["fulfillment_status"] == "已出貨" else "green")
                st.markdown(f"**配送狀態：<span style='color:{status_color}'>{c['fulfillment_status']}</span>**", unsafe_allow_html=True)
            
            with col_action:
                st.write("") # 排版用
                # 💡 供給方(企業) 的視角：標記出貨
                if user.get("id") == s.get("provider_id") and c["fulfillment_status"] == "待出貨":
                    if st.button("🚚 標記為『已出貨』", key=f"ship_{c['id']}", use_container_width=True):
                        c["fulfillment_status"] = "已出貨"
                        add_notification(f"物流更新：訂單 {c['id']} 物資已出發前往 {d.get('location')}", "logistics")
                        st.rerun()
                        
                # 💡 需求方(災民/村長) 的視角：確認收妥
                elif user.get("id") == d.get("requester_id") and c["fulfillment_status"] == "已出貨":
                    if st.button("✅ 確認『已安全送達』", key=f"deliver_{c['id']}", type="primary", use_container_width=True):
                        c["fulfillment_status"] = "已完成(收妥)"
                        add_notification(f"任務結案：訂單 {c['id']} 物資已安全送達災民手中！", "logistics")
                        st.rerun()


def page_esg_dashboard():
    user = get_current_user()
    st.title("📈 企業 ESG 社會影響力與捐贈報告")
    st.caption("彙整貴單位於平台上的所有救災行動，支援一鍵生成 CSR/ESG 永續報告草稿。")
    
    related_claims = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id") and c.get("status") == "approved"]
    
    if not related_claims:
        st.info("目前尚未有已完成配對的捐贈行動。")
        return
        
    # 影響力數據面板
    total_items = sum(c.get("claim_qty", 0) for c in related_claims)
    districts_helped = set()
    data = []
    
    for c in related_claims:
        d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), {})
        s = next((x for x in st.session_state.supplies if x.get("id") == c.get("supply_id")), {})
        districts_helped.add(d.get("district", "未知地區"))
        data.append({
            "時間": c.get("time"),
            "支援地區": d.get("location", ""),
            "捐贈物資": s.get("item", ""),
            "數量": c.get("claim_qty"),
            "物流模式": s.get("has_logistics", "可自行運送")
        })
        
    col1, col2, col3 = st.columns(3)
    col1.metric("總計捐贈物資數量", f"{total_items} 件")
    col2.metric("馳援災區數量", f"{len(districts_helped)} 處")
    col3.metric("完成調度任務", f"{len(related_claims)} 次")
    
    st.divider()
    st.subheader("📋 詳細出貨與支援紀錄")
    st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)
    
    st.divider()
    if st.button("✨ 一鍵生成 ESG 影響力報告 (AI 草稿)", type="primary"):
        with st.spinner("AI 正在整合數據並撰寫公關報告..."):
            prompt = f"""
            你是一個專業的企業公關與永續發展(ESG)撰稿專家。
            請根據以下 {user.get('name')} 的救災數據，寫一篇大約 300 字的動人新聞稿/ESG報告草稿：
            馳援地區：{', '.join(districts_helped)}
            共計捐贈物資數：{total_items}件
            詳細清單：{json.dumps(data, ensure_ascii=False)}
            
            請強調企業社會責任(CSR)、快速響應災情、以及與 ResQ-Link 平台協作達成精準救援。
            使用 Markdown 格式。
            """
            try:
                from openai import OpenAI
                client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
                res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.3)
                report_md = res.choices[0].message.content
                st.success("報告生成完畢！")
                st.markdown(f"> {report_md}")
                
                st.download_button(
                    label="📥 下載報告為 Markdown 檔",
                    data=report_md,
                    file_name=f"{user.get('name')}_ESG_Report.md",
                    mime="text/markdown"
                )
            except Exception as e:
                st.error("生成報告失敗。")


def page_profile():
    user = get_current_user()
    st.title("👤 個人資料")
    st.write(f"名稱：{user.get('name')}")
    st.write(f"角色：{ROLE_LABELS.get(user.get('role'))}")
    st.write(f"Email：{user.get('email')}")
    st.write(f"手機：{user.get('phone', '未填')}｜{'✅ 手機已驗證' if user.get('phone_verified') else '⚪ 手機未驗證'}")
    st.write(f"行政區 / 村里：{user.get('district')} / {user.get('village')}")
    st.write(f"認證狀態：{'✅ 已認證' if user.get('verified') else '⚪ 未認證 / 待審'}")
    st.caption(f"證明資料：{user.get('proof')}")


def page_gov_supply_review():
    user = get_current_user()
    st.title("📦 供給審核")
    st.caption("政府單位可審核轄區內的供給資料，平台管理員則可審核全平台供給。")
    if user.get("role") == "admin":
        rows = [s for s in st.session_state.supplies if s.get("verification_status") == "pending"]
    else:
        rows = [s for s in st.session_state.supplies if s.get("verification_status") == "pending" and can_gov_review(user, s)]
    if not rows:
        st.info("目前沒有可審核供給。")
        return
    for s in rows:
        with st.container(border=True):
            st.markdown(f"### [{s.get('id')}] {s.get('provider')}｜{s.get('item')} x {s.get('qty')}")
            st.write(f"地區：{s.get('district')} / {s.get('village')}｜分類：{s.get('resource_type')} / {s.get('category')}")
            note = st.text_input("審核備註", key=f"supply_review_note_{s.get('id')}")
            col1, col2 = st.columns(2)
            if col1.button("✅ 供給認證通過", key=f"supply_review_ok_{s.get('id')}"):
                s["verification_status"] = "verified"
                s["verified_by"] = user.get("id")
                add_audit("認證供給", f"{s.get('id')} / {note}")
                st.rerun()
            if col2.button("❌ 駁回供給", key=f"supply_review_no_{s.get('id')}"):
                s["verification_status"] = "rejected"
                s["status"] = "已駁回"
                s["risk_flag"] = note or "供給審核駁回"
                add_audit("駁回供給", f"{s.get('id')} / {note}")
                st.rerun()


def page_transfer_settings():
    user = get_current_user()
    st.title("📍 轄區設定")
    st.caption("Demo 版可在這裡查看政府單位的審核範圍；正式版可串接行政區資料庫。")
    st.info(f"目前帳號可審核範圍：{user.get('district')} / {user.get('village')}")
    st.write("審核規則：政府單位只能審核同一行政區，若村里不是『全區』，則只能審核同村里資料。")


def page_system_overview():
    st.title("📈 系統總覽")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("需求總數", len(st.session_state.demands))
    col2.metric("供給總數", len(st.session_state.supplies))
    col3.metric("認領申請", len(st.session_state.claims))
    col4.metric("通知數", len(st.session_state.notifications))
    st.divider()
    st.subheader("狀態分布")
    st.dataframe(pd.DataFrame({
        "項目": ["已認證需求", "待認證需求", "已認證供給", "待認證供給", "已核准認領", "待審認領", "待審智慧配對"],
        "數量": [
            len([d for d in st.session_state.demands if d.get("verification_status") == "verified"]),
            len([d for d in st.session_state.demands if d.get("verification_status") == "pending"]),
            len([s for s in st.session_state.supplies if s.get("verification_status") == "verified"]),
            len([s for s in st.session_state.supplies if s.get("verification_status") == "pending"]),
            len([c for c in st.session_state.claims if c.get("status") == "approved"]),
            len([c for c in st.session_state.claims if c.get("status") == "pending_gov_review"]),
            len([m for m in st.session_state.smart_matches if m.get("status") == "pending_admin_review"]),
        ]
    }), hide_index=True, use_container_width=True)


def page_system_settings():
    st.title("⚙️ 系統設定")
    st.caption("這裡是 Demo 設定頁，讓架構符合管理員可調整分類、通知與權限的概念。")
    st.subheader("目前資源分類")
    st.json(RESOURCE_TYPES)
    st.subheader("通知設定")
    st.write("Email：", "已設定 SMTP" if SMTP_HOST and SMTP_USER else "Demo 模式，只寫入 Email 紀錄")
    st.subheader("權限設定")
    st.write("一般民眾：提出需求、建立供給、認領需求、查看自己的紀錄")
    st.write("公司/團體：建立供給、認領需求、查看配對與捐贈紀錄")
    st.write("政府單位：審核轄區需求與供給、審核認領、AI 調配")
    st.write("平台管理員：全平台總控、帳號審核、資料下架、異常標記、稽核紀錄")
    st.write("手機 OTP：Demo 版只顯示在註冊當下畫面，不進入全站通知中心；正式版可串接 SMS API，OTP 5 分鐘有效。")

# =========================================================
# 7. Main App
# =========================================================
st.set_page_config(page_title="ResQ-Link 可信任災害資源分配平台", layout="wide", page_icon="🧩")
init_session_state()

if not is_logged_in():
    login_panel()
    st.stop()

sidebar_layout()
user = get_current_user()
role = user.get("role")

role_pages = {
    "citizen": [
        "💬 智慧對話通報", "🗺️ 災情與資源地圖", "🤝 協助與認領", "📌 我的紀錄", "👤 個人設定與表單"
    ],
    "company": [
        "📊 公司總覽",
        "💬 AI供給登錄",
        "📦 供給與認領中心",
        "🚚 配對物流與 ESG",
        "🗺️ 公開資源池",
        "👤 個人設定",
    ],
    # 💡 政府介面大瘦身：留下最精華的決策與協作功能
    "government": [
        "📥 戰情收件匣",         # 取代舊有儀表板
        "🤖 AI 指揮官助理",      # 核心亮點！
        "✅ 需求與認領審核",     # 保留你上一階段優化過的批次審核+地圖
        "🗺️ 災情與資源地圖",     # 掌握全局空間
        "🚚 配對與物流管理",     # 出貨與結案
        "👤 個人設定與表單"      # 收納備用表單與設定
    ],
    "admin": [
        "📈 系統總覽", "🛡️ 管理員總控台"
    ],
}

page = st.sidebar.radio("功能選單", role_pages.get(role, ["📊 儀表板"]))

# =========================================================
# 路由綁定 (將新舊功能連接)
# =========================================================
if page in ["💬 智慧對話通報", "💬 對話通報"]:
    page_chatbot()
elif page == "🤖 AI 指揮官助理":    # 💡 綁定政府新 AI 助理
    page_gov_chatbot()
elif page == "📥 戰情收件匣":       # 💡 綁定政府新首頁
    page_gov_inbox()
elif page in ["🏠 首頁", "📊 儀表板", "📊 公司總覽"]:
    page_role_dashboard()
elif page in ["🗺️ 資源池", "🗺️ 公開資源池", "🗺️ 災情與資源地圖"]:
    page_map_pool()
elif page in ["🤝 我要認領需求", "🤝 協助與認領"]:
    page_public_claims()
elif page == "📌 我的紀錄":
    st.title("📌 我的通報與認領紀錄")
    tab1, tab2, tab3 = st.tabs(["我的需求", "我的供給", "我的認領申請"])
    with tab1: page_my_demands()
    with tab2: page_my_supplies()
    with tab3: page_my_claims()
elif page == "👤 個人設定與表單":
    st.title("👤 設定與備用表單")
    if role == "company":
        tabs = st.tabs(["個人資料", "通知紀錄", "填寫供給表單"])
        with tabs[0]: page_profile()
        with tabs[1]: st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
        with tabs[2]: page_submit_supply()
    elif role in ["government", "citizen"]:
        tabs = st.tabs(["個人資料", "通知紀錄", "填寫需求表單", "填寫供給表單"])
        with tabs[0]: page_profile()
        with tabs[1]: st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
        with tabs[2]: page_submit_demand()
        with tabs[3]: page_submit_supply()
    else:
        tabs = st.tabs(["個人資料", "通知紀錄"])
        with tabs[0]: page_profile()
        with tabs[1]: st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)

elif page == "💬 AI供給登錄":
    page_company_supply_chatbot()
elif page == "📦 供給與認領中心":
    page_company_supply_claim_center()
elif page == "🚚 配對物流與 ESG":
    page_company_logistics_esg_center()
elif page == "👤 個人設定":
    page_profile()

# 以下保留給企業與管理員的專屬功能
elif page in ["📦 建立供給(含批次)", "📦 建立供給"]:
    page_submit_supply()
elif page == "📦 我提供的供給":
    page_my_supplies()
elif page == "📋 我的認領申請":
    page_my_claims()
elif page in ["✅ 需求審核", "📋 認領申請審核", "✅ 需求與認領審核"]: # 💡 對接政府的審核頁面
    page_gov_review()
elif page in ["🪪 認證管理", "🧾 帳號審核管理", "📌 需求管理", "📦 供給管理", "📋 認領申請總審核", "🔔 通知與Email紀錄", "📜 稽核紀錄", "🛡️ 管理員總控台"]:
    page_admin()
elif page in ["🚚 已配對訂單", "🚚 配對管理", "🚚 配對與物流管理"]:
    page_matched_orders()
elif page in ["📈 企業 ESG 影響力", "💰 捐款/捐贈紀錄", "💰 我要捐款/捐贈紀錄"]:
    page_esg_dashboard() 
elif page == "📈 系統總覽":
    page_system_overview()
elif page == "📥 AI轉譯":
    page_multimodal()
else:
    if role == "government":
        page_gov_inbox()
    else:
        page_role_dashboard()

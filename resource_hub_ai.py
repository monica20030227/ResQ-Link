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
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
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
    if not gov_user or gov_user.get("role") != "government":
        return False
    if gov_user.get("district") == "全區":
        return True
    same_district = gov_user.get("district") == record.get("district")
    gov_village = gov_user.get("village", "全區")
    same_village = gov_village in ["全區", ""] or gov_village == record.get("village")
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
    if not GROQ_API_KEY:
        return {"error": "尚未設定 GROQ_API_KEY"}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        categories_text = json.dumps(RESOURCE_TYPES, ensure_ascii=False)
        system_prompt = f"""
你是一個專業防災資源調度員。判斷輸入是 Demand 或 Supply，並萃取為 JSON。
請優先使用以下分類：{categories_text}
回傳格式：
{{
  "info_type": "Demand 或 Supply",
  "data": {{
    "location": "若是 Demand 填地點，Supply 留空",
    "provider": "若是 Supply 填提供者，Demand 留空",
    "location_current": "若是 Supply 填所在地，Demand 留空",
    "district": "行政區，例如 花蓮縣壽豐鄉",
    "village": "村里，未知則填 全區",
    "resource_type": "有形資源/無形資源/金流資源",
    "category": "分類",
    "item": "具體品項",
    "qty": 數量整數,
    "urgency": 緊急度1-5,
    "lat": 緯度浮點數,
    "lon": 經度浮點數
  }}
}}
"""
        messages = [{"role": "system", "content": system_prompt}]
        if image_bytes:
            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": str(raw_text)},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}},
                    ],
                }
            )
            model_name = "meta-llama/llama-4-scout-17b-16e-instruct"
        else:
            messages.append({"role": "user", "content": str(raw_text)})
            model_name = "llama-3.3-70b-versatile"

        res = client.chat.completions.create(model=model_name, messages=messages, temperature=0.0)
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find("{")
        end_idx = raw_output.rfind("}")
        if start_idx != -1 and end_idx != -1:
            return json.loads(raw_output[start_idx : end_idx + 1])
        return {"error": "格式異常", "raw": raw_output}
    except Exception as e:
        return {"error": str(e)}


def ai_match_resources(target_demand, available_supplies):
    if not GROQ_API_KEY:
        return [{"error": "尚未設定 GROQ_API_KEY"}]
    try:
        from openai import OpenAI

        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        supplies_str = json.dumps(available_supplies, ensure_ascii=False, indent=2)
        demand_str = json.dumps(target_demand, ensure_ascii=False, indent=2)
        prompt = f"""
你是一個防災資源調度 AI 系統。前線需求：\n{demand_str}\n\n可調派供給：\n{supplies_str}
請依據【地理空間距離】、【資源分類】、【品項語意吻合】、【數量】、【認證狀態】評估。
必須輸出 JSON 陣列 `[...]`，包含 `supply_id`, `match_score`, `reason`。
"""
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find("[")
        end_idx = raw_output.rfind("]")
        if start_idx != -1 and end_idx != -1:
            parsed_data = json.loads(raw_output[start_idx : end_idx + 1])
            return parsed_data if isinstance(parsed_data, list) else [parsed_data]
        return [{"error": "解析失敗", "raw": raw_output}]
    except Exception as e:
        return [{"error": str(e)}]

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
    with st.expander("➕ 註冊新帳號（含手機 OTP 驗證）"):
        st.info("流程：填寫資料 → 發送手機 OTP → 輸入驗證碼 → 送出註冊。Demo 版只會在目前畫面顯示 OTP，不會放到全站通知中心。正式版可改接簡訊 API。")
        with st.form("signup_form"):
            new_role = st.selectbox("帳號類型", ["citizen", "company", "government"], format_func=lambda x: ROLE_LABELS[x])
            name = st.text_input("姓名 / 單位名稱")
            email = st.text_input("Email")
            phone = st.text_input("手機號碼", placeholder="例如：0912345678 或 +886912345678")
            district = st.text_input("行政區", placeholder="例如：花蓮縣壽豐鄉")
            village = st.text_input("村里", value="全區")
            proof = st.text_area("證明資料", placeholder="政府單位可填公務信箱、職稱、服務單位；公司可填統編或網站；民眾可填聯絡資訊。")
            otp_code = st.text_input("手機 OTP 驗證碼", placeholder="請輸入 6 碼驗證碼")

            col_otp, col_submit = st.columns(2)
            send_otp_btn = col_otp.form_submit_button("📱 發送手機 OTP")
            submitted = col_submit.form_submit_button("✅ 送出註冊", type="primary")

        phone_norm = normalize_phone(phone)

        if send_otp_btn:
            if not phone_norm or not is_valid_phone(phone_norm):
                st.error("請輸入有效手機號碼，例如 0912345678 或 +886912345678。")
            else:
                otp = send_phone_otp(phone_norm)
                st.success(f"OTP 已送出至 {phone_norm}。Demo 驗證碼：{otp}（只顯示給目前註冊者，不會進入通知中心）")

        if submitted:
            if not name or not email or not district or not phone_norm:
                st.error("請至少填寫名稱、Email、手機號碼、行政區。")
            elif not is_valid_phone(phone_norm):
                st.error("手機號碼格式不正確，請使用 0912345678 或 +886912345678。")
            else:
                ok, msg = verify_phone_otp(phone_norm, otp_code)
                if not ok:
                    st.error(msg)
                    return

                verified = False
                status = "pending" if new_role in ["government", "company"] else "active"
                if new_role == "government" and email.endswith(".gov.tw"):
                    verified = False
                    status = "pending"

                new_user = {
                    "id": make_id("U"),
                    "name": name,
                    "role": new_role,
                    "email": email,
                    "phone": phone_norm,
                    "phone_verified": True,
                    "district": district,
                    "village": village or "全區",
                    "verified": verified,
                    "status": status,
                    "proof": proof,
                }
                st.session_state.users.append(new_user)
                add_audit("新帳號註冊", f"{name} / {ROLE_LABELS[new_role]} / phone_verified=True / status={status}")
                # 手機驗證通過屬於個人驗證事件，不寫入全站通知中心。
                if status == "pending":
                    st.success("手機 OTP 驗證成功，註冊已送出，需等待平台管理員審核後才能登入。")
                else:
                    st.success("手機 OTP 驗證成功，註冊完成，可回上方登入。")

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
    st.title("📣 提出需求")
    st.caption("一般民眾提出後會標示為待認證；政府單位提出會直接顯示已認證。")
    with st.form("demand_form"):
        location = st.text_input("需求地點", value=user.get("district", ""))
        district = st.text_input("行政區", value=user.get("district", ""))
        village = st.text_input("村里", value=user.get("village", "全區"))
        resource_type, category = resource_selectors("demand")
        item = st.text_input("需求品項", placeholder="例如：礦泉水、抽水機、志工人力")
        qty = st.number_input("需求數量", min_value=1, value=1)
        urgency = st.slider("緊急程度", 1, 5, 3)
        lat = st.number_input("緯度", value=23.8, format="%.6f")
        lon = st.number_input("經度", value=121.0, format="%.6f")
        raw_text = st.text_area("補充說明")
        submitted = st.form_submit_button("送出需求", type="primary")

    if submitted:
        if not item or not location:
            st.error("請填寫地點與品項。")
            return
        verification_status = "verified" if user.get("role") == "government" and user.get("verified") else "pending"
        demand = {
            "id": make_id("D"),
            "time": now_str(),
            "source": "平台表單",
            "requester_id": user.get("id"),
            "requester_name": user.get("name"),
            "requester_email": user.get("email"),
            "district": district,
            "village": village or "全區",
            "location": location,
            "lat": lat,
            "lon": lon,
            "resource_type": resource_type,
            "category": category,
            "item": item,
            "qty": int(qty),
            "urgency": urgency,
            "status": "未處理",
            "matched_provider": "",
            "verification_status": verification_status,
            "verified_by": user.get("id") if verification_status == "verified" else "",
            "raw_text": raw_text,
            "risk_flag": "",
        }
        st.session_state.demands.insert(0, demand)
        add_audit("新增需求", f"{demand['id']} / {item} x {qty}")
        if verification_status == "pending":
            add_notification(f"🟡 新民眾需求待地方政府審核：{district} {item}", "review")
            st.success("需求已送出，目前為待認證。")
        else:
            st.success("政府單位需求已送出，並標示為已認證。")


def page_submit_supply():
    user = get_current_user()
    st.title("📦 建立供給")
    st.caption("一般民眾、公司/團體、政府單位都可以建立供給。未認證供給也可被管理員或政府單位檢視。")
    with st.form("supply_form"):
        provider = st.text_input("提供者名稱", value=user.get("name", ""))
        location_current = st.text_input("目前所在地", value=user.get("district", ""))
        district = st.text_input("行政區", value=user.get("district", ""))
        village = st.text_input("村里", value=user.get("village", "全區"))
        resource_type, category = resource_selectors("supply")
        item = st.text_input("可提供品項", placeholder="例如：礦泉水、抽水機、志工人力、捐款")
        qty = st.number_input("可提供數量", min_value=1, value=1)
        lat = st.number_input("緯度", value=23.8, format="%.6f", key="supply_lat")
        lon = st.number_input("經度", value=121.0, format="%.6f", key="supply_lon")
        raw_text = st.text_area("補充說明", key="supply_note")
        submitted = st.form_submit_button("建立供給", type="primary")

    if submitted:
        if not item or not provider:
            st.error("請填寫提供者與品項。")
            return
        verification_status = "verified" if user.get("verified") else "pending"
        supply = {
            "id": make_id("S"),
            "time": now_str(),
            "source": "平台表單",
            "provider_id": user.get("id"),
            "provider": provider,
            "provider_email": user.get("email"),
            "district": district,
            "village": village or "全區",
            "location_current": location_current,
            "lat": lat,
            "lon": lon,
            "resource_type": resource_type,
            "category": category,
            "item": item,
            "qty": int(qty),
            "status": "可調派",
            "verification_status": verification_status,
            "verified_by": user.get("id") if verification_status == "verified" else "",
            "raw_text": raw_text,
            "risk_flag": "",
        }
        st.session_state.supplies.insert(0, supply)
        add_audit("新增供給", f"{supply['id']} / {item} x {qty}")
        st.success("供給已建立。")


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

    tab1, tab2 = st.tabs(["需求認證", "認領申請審核"])

    with tab1:
        reviewable_demands = [d for d in st.session_state.demands if d.get("verification_status") == "pending" and can_gov_review(user, d)]
        if not reviewable_demands:
            st.info("目前沒有你可審核的需求。")
        for d in reviewable_demands:
            with st.container(border=True):
                demand_card(d)
                col_a, col_b = st.columns(2)
                note = st.text_input("審核備註", key=f"gov_d_note_{d['id']}")
                if col_a.button("✅ 認證通過", key=f"gov_approve_d_{d['id']}"):
                    d["verification_status"] = "verified"
                    d["verified_by"] = user.get("id")
                    add_audit("政府認證需求", f"{d['id']} 通過 / {note}")
                    add_notification(f"✅ 需求已由 {user.get('name')} 認證：{d.get('item')}", "review")
                    st.rerun()
                if col_b.button("❌ 駁回需求", key=f"gov_reject_d_{d['id']}"):
                    d["verification_status"] = "rejected"
                    d["status"] = "已駁回"
                    d["risk_flag"] = note or "地方政府駁回"
                    add_audit("政府駁回需求", f"{d['id']} / {note}")
                    st.rerun()

    with tab2:
        reviewable_claims = []
        for c in st.session_state.claims:
            if c.get("status") != "pending_gov_review":
                continue
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            if d and can_gov_review(user, d):
                reviewable_claims.append(c)

        if not reviewable_claims:
            st.info("目前沒有你可審核的認領申請。")
        for c in reviewable_claims:
            d = next((x for x in st.session_state.demands if x["id"] == c["demand_id"]), None)
            s = next((x for x in st.session_state.supplies if x["id"] == c["supply_id"]), None)
            if not d or not s:
                continue
            with st.container(border=True):
                st.markdown(f"### 申請 {c['id']}｜{c['claimant_name']} 認領 {d.get('item')} x {c.get('claim_qty')}")
                st.write(f"需求：{d.get('location')}｜{badge_text(d.get('verification_status'))}")
                st.write(f"供給：{s.get('provider')} / {s.get('item')}｜庫存 {s.get('qty')}｜{badge_text(s.get('verification_status'))}")
                st.progress(min(c.get("match_score", 0), 100) / 100, text=f"系統媒合分數：{c.get('match_score')}｜{c.get('match_reason')}")
                note = st.text_input("審核備註", key=f"gov_c_note_{c['id']}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ 核准認領並完成配對", key=f"gov_approve_c_{c['id']}"):
                    c["reviewer"] = user.get("name")
                    c["review_note"] = note or "地方政府審核通過"
                    ok = execute_dispatch(d["id"], s["id"], s.get("provider"), c.get("claim_qty"), claim_id=c["id"])
                    if ok:
                        st.success("已完成配對。")
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
    st.caption("可將文字或圖片自動轉成需求/供給資料。")
    col_in, col_out = st.columns(2)
    with col_in:
        uploaded_file = st.file_uploader("上傳災情或物資照片", type=["jpg", "jpeg", "png"])
        raw_text_input = st.text_area("補充文字", placeholder="例如：我們這裡需要抽水機 5 台")
        if st.button("🧠 啟動解析", type="primary"):
            img_bytes = uploaded_file.getvalue() if uploaded_file else None
            mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
            text_to_send = raw_text_input or "請根據圖片判斷災情與需求。"
            result = extract_info_with_ai(text_to_send, img_bytes, mime_type)
            with col_out:
                st.json(result)
            if "error" in result:
                st.error(result["error"])
                return
            user = get_current_user()
            extracted = result.get("data", result)
            is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
            if is_demand:
                record = {
                    "id": make_id("D"),
                    "time": now_str(),
                    "source": "AI轉譯",
                    "requester_id": user.get("id"),
                    "requester_name": user.get("name"),
                    "requester_email": user.get("email"),
                    "status": "未處理",
                    "matched_provider": "",
                    "verification_status": "verified" if user.get("role") == "government" and user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("role") == "government" and user.get("verified") else "",
                    "raw_text": text_to_send,
                    "risk_flag": "",
                }
                record.update(extracted)
                record.setdefault("village", "全區")
                st.session_state.demands.insert(0, record)
                st.success("已寫入需求池。")
            else:
                record = {
                    "id": make_id("S"),
                    "time": now_str(),
                    "source": "AI轉譯",
                    "provider_id": user.get("id"),
                    "provider": extracted.get("provider") or user.get("name"),
                    "provider_email": user.get("email"),
                    "status": "可調派",
                    "verification_status": "verified" if user.get("verified") else "pending",
                    "verified_by": user.get("id") if user.get("verified") else "",
                    "raw_text": text_to_send,
                    "risk_flag": "",
                }
                record.update(extracted)
                if "location" in record and "location_current" not in record:
                    record["location_current"] = record["location"]
                record.setdefault("village", "全區")
                st.session_state.supplies.insert(0, record)
                st.success("已寫入供給池。")
            add_audit("AI 多模態轉譯寫入資料", "Demand" if is_demand else "Supply")


def page_chatbot():
    st.title("💬 前線對話通報")
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    if user_input := st.chat_input("請輸入需求或供給內容..."):
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            result = extract_info_with_ai(raw_text=user_input)
            if "error" in result:
                reply = "抱歉，AI 解析失敗。請改用表單輸入，或檢查 GROQ_API_KEY。"
            else:
                extracted = result.get("data", result)
                is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
                user = get_current_user()
                if is_demand:
                    record = {
                        "id": make_id("D"), "time": now_str(), "source": "對話通報",
                        "requester_id": user.get("id"), "requester_name": user.get("name"), "requester_email": user.get("email"),
                        "status": "未處理", "matched_provider": "", "verification_status": "pending", "verified_by": "", "raw_text": user_input, "risk_flag": "",
                    }
                    record.update(extracted)
                    record.setdefault("village", "全區")
                    st.session_state.demands.insert(0, record)
                else:
                    record = {
                        "id": make_id("S"), "time": now_str(), "source": "對話通報",
                        "provider_id": user.get("id"), "provider": extracted.get("provider") or user.get("name"), "provider_email": user.get("email"),
                        "status": "可調派", "verification_status": "verified" if user.get("verified") else "pending", "verified_by": "", "raw_text": user_input, "risk_flag": "",
                    }
                    record.update(extracted)
                    if "location" in record and "location_current" not in record:
                        record["location_current"] = record["location"]
                    record.setdefault("village", "全區")
                    st.session_state.supplies.insert(0, record)
                reply = f"✅ 已立案：{record.get('item', '未知')} x {record.get('qty', 1)}"
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})



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
        with st.container(border=True):
            st.markdown(f"### ✅ 訂單 {c.get('id')}｜{s.get('provider')} → {d.get('location')}")
            st.write(f"物資：{d.get('item')} x {c.get('claim_qty')}｜需求狀態：{d.get('status')}")
            st.write(f"通知：已寄送 Email / 站內通知（Demo 紀錄可於管理員總控台查看）")


def page_donation_records():
    user = get_current_user()
    st.title("💰 捐款 / 捐贈紀錄")
    related_claims = [c for c in st.session_state.claims if c.get("claimant_id") == user.get("id")]
    if not related_claims:
        st.info("目前沒有捐贈或認領紀錄。")
        return
    data = []
    for c in related_claims:
        d = next((x for x in st.session_state.demands if x.get("id") == c.get("demand_id")), {})
        s = next((x for x in st.session_state.supplies if x.get("id") == c.get("supply_id")), {})
        data.append({
            "申請編號": c.get("id"),
            "需求地點": d.get("location", ""),
            "提供項目": s.get("item", ""),
            "數量": c.get("claim_qty"),
            "狀態": CLAIM_STATUS.get(c.get("status"), c.get("status")),
            "時間": c.get("time"),
        })
    st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)


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

# 依架構圖顯示不同角色的功能選單
role_pages = {
    "citizen": [
        "📊 儀表板", "📌 我的需求", "📣 我要提出需求", "🤝 我要認領需求", "📋 我的認領申請",
        "💰 我要捐款/捐贈紀錄", "🔔 通知紀錄", "👤 個人資料", "🗺️ 公開資源池", "💬 對話通報", "📥 AI轉譯"
    ],
    "company": [
        "📊 儀表板", "📦 我提供的供給", "📦 建立供給", "🤝 我要認領需求", "📋 我的認領申請",
        "🚚 已配對訂單", "💰 捐款/捐贈紀錄", "🔔 通知紀錄", "🗺️ 公開資源池", "📥 AI轉譯"
    ],
    "government": [
        "📊 儀表板", "✅ 需求審核", "📦 供給審核", "🪪 認證管理", "📋 認領申請審核",
        "🚚 配對管理", "📍 轄區設定", "🔔 通知紀錄", "🗺️ 公開資源池", "🤖 AI調配", "📣 我要提出需求", "📦 建立供給", "📥 AI轉譯"
    ],
    "admin": [
        "📈 系統總覽", "🛡️ 管理員總控台"
    ],
}

page = st.sidebar.radio("功能選單", role_pages.get(role, ["📊 儀表板"]))

if page in ["🏠 首頁", "📊 儀表板"]:
    page_role_dashboard()
elif page in ["📣 提出需求", "📣 我要提出需求"]:
    page_submit_demand()
elif page == "📌 我的需求":
    page_my_demands()
elif page in ["📦 建立供給"]:
    page_submit_supply()
elif page == "📦 我提供的供給":
    page_my_supplies()
elif page == "🤝 我要認領需求":
    page_public_claims()
elif page == "📋 我的認領申請":
    page_my_claims()
elif page in ["✅ 需求審核", "📋 認領申請審核"]:
    page_gov_review()
elif page == "📦 供給審核":
    page_gov_supply_review()
elif page == "🧠 智慧配對審核":
    page_smart_match_review()
elif page in ["🪪 認證管理", "🧾 帳號審核管理", "📌 需求管理", "📦 供給管理", "📋 認領申請總審核", "🔔 通知與Email紀錄", "📜 稽核紀錄"]:
    page_admin()
elif page == "🛡️ 管理員總控台":
    page_admin()
elif page in ["🗺️ 資源池", "🗺️ 公開資源池"]:
    page_map_pool()
elif page in ["🚚 已配對訂單", "🚚 配對管理"]:
    page_matched_orders()
elif page in ["💰 捐款/捐贈紀錄", "💰 我要捐款/捐贈紀錄"]:
    page_donation_records()
elif page == "📍 轄區設定":
    page_transfer_settings()
elif page == "📈 系統總覽":
    page_system_overview()
elif page == "⚙️ 系統設定":
    page_system_settings()
elif page == "🤖 AI調配":
    page_ai_match()
elif page == "📥 AI轉譯":
    page_multimodal()
elif page == "💬 對話通報":
    page_chatbot()
elif page == "🔔 通知紀錄":
    st.title("🔔 通知紀錄")
    st.dataframe(pd.DataFrame(st.session_state.notifications), hide_index=True, use_container_width=True)
else:
    page_role_dashboard()

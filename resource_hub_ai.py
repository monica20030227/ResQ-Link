import os
import time
import json
import base64
import smtplib
import math
import pandas as pd
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

# ============================================================
# 0. 常數設定
# ============================================================
RESOURCE_TAXONOMY = {
    "有形資源": ["食物", "飲用水", "醫療用品", "生活用品", "家具", "救災工具", "交通工具", "重型機具", "通訊設備", "臨時住所"],
    "無形資源": ["人力", "志工", "專業技術", "醫療支援", "心理諮詢", "運輸協助", "資訊彙整", "翻譯協助"],
    "金流資源": ["現金捐款", "物資採購金", "專案補助", "企業贊助"]
}
ROLE_OPTIONS = ["一般民眾", "政府單位", "公司/NGO/志工團體"]
GOV_DOMAIN_HINTS = ["gov.tw", "mail.gov.tw", "nfa.gov.tw", "moea.gov.tw", "mohw.gov.tw", "ems.gov.tw"]
VERIFIED = "✅ 已認證"
PENDING = "🟡 待認證"
UNVERIFIED = "⚪ 未認證"

# ============================================================
# 1. 基礎工具
# ============================================================
def now_str(fmt="%Y-%m-%d %H:%M"):
    return datetime.now().strftime(fmt)


def generate_id(prefix):
    return f"{prefix}{int(time.time() * 1000) % 1000000:06d}"


def guess_resource_type(category):
    for rt, cats in RESOURCE_TAXONOMY.items():
        if category in cats:
            return rt
    return "有形資源"


def all_categories():
    cats = []
    for v in RESOURCE_TAXONOMY.values():
        cats.extend(v)
    return cats


def is_gov_email(email):
    email = (email or "").lower()
    return any(domain in email for domain in GOV_DOMAIN_HINTS)


def same_admin_area(gov_area, demand_area_or_location):
    """Demo 用：只要行政區文字互相包含，就視為同一區/里可審核。"""
    gov_area = (gov_area or "").replace("台", "臺").strip()
    loc = (demand_area_or_location or "").replace("台", "臺").strip()
    if not gov_area or not loc:
        return False
    return gov_area in loc or loc in gov_area or gov_area[:5] in loc


def haversine_km(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    except Exception:
        return None
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_badge(record):
    if record.get("blue_check") or record.get("verification_status") == VERIFIED:
        return "✅ 藍勾勾已認證"
    return record.get("verification_status", UNVERIFIED)


def add_notification(msg, notif_type="system"):
    st.session_state.notifications.insert(0, {"time": now_str("%H:%M:%S"), "msg": msg, "type": notif_type})


def send_email(to_email, subject, body):
    """有 SMTP 就真的寄；沒有 SMTP 就留下 Demo 寄信紀錄。"""
    if not to_email:
        status = "略過：未提供收件者"
    elif SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM:
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
        except Exception as e:
            status = f"寄送失敗：{e}"
    else:
        status = "Demo 模式：未設定 SMTP，已建立模擬寄信紀錄"

    st.session_state.email_logs.insert(0, {
        "time": now_str("%Y-%m-%d %H:%M:%S"),
        "to": to_email or "未提供 Email",
        "subject": subject,
        "body": body,
        "status": status
    })


def send_match_emails(demand, supply, qty, mode):
    demand_subject = f"【ResQ-Link】您的需求已完成{mode}"
    demand_body = f"""您好，您的救災需求已成功媒合。

需求編號：{demand.get('id')}
需求地點：{demand.get('location')}
需求項目：{demand.get('item')}
支援數量：{qty}
供給方：{supply.get('provider')}
供給方 Email：{supply.get('provider_email', '未提供')}
需求認證狀態：{demand.get('verification_status')}

請保持聯絡方式暢通，等待後續聯繫。
"""
    supply_subject = f"【ResQ-Link】您已成功媒合一筆救災需求"
    supply_body = f"""您好，您的供給已成功媒合一筆救災需求。

需求編號：{demand.get('id')}
需求地點：{demand.get('location')}
需求項目：{demand.get('item')}
支援數量：{qty}
需求方：{demand.get('requester')}
需求方 Email：{demand.get('requester_email', '未提供')}
需求認證狀態：{demand.get('verification_status')}

請依照平台資訊與需求方聯繫，並保留運送/捐贈紀錄。
"""
    send_email(demand.get("requester_email", ""), demand_subject, demand_body)
    send_email(supply.get("provider_email", ""), supply_subject, supply_body)

# ============================================================
# 2. Session State 初始化
# ============================================================
def init_session_state():
    now = datetime.now()
    if "users" not in st.session_state:
        st.session_state.users = [
            {
                "user_id": "U001", "name": "花蓮壽豐鄉公所", "role": "政府單位",
                "email": "shoufeng@gov.tw", "phone": "03-0000000", "area": "花蓮縣壽豐鄉",
                "org": "花蓮壽豐鄉公所", "title": "承辦人", "verification_status": VERIFIED,
                "blue_check": True, "signup_time": now_str()
            },
            {
                "user_id": "U002", "name": "統一企業", "role": "公司/NGO/志工團體",
                "email": "csr@example.com", "phone": "06-0000000", "area": "台南市永康區",
                "org": "統一企業", "title": "CSR窗口", "verification_status": PENDING,
                "blue_check": False, "signup_time": now_str()
            },
            {
                "user_id": "U003", "name": "壽豐居民王小姐", "role": "一般民眾",
                "email": "resident@example.com", "phone": "09xx-xxx-xxx", "area": "花蓮縣壽豐鄉",
                "org": "", "title": "", "verification_status": UNVERIFIED,
                "blue_check": False, "signup_time": now_str()
            }
        ]

    if "current_user" not in st.session_state:
        st.session_state.current_user = None

    if "demands" not in st.session_state:
        st.session_state.demands = [
            {
                "id": "D001", "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"),
                "source": "政府通報", "requester": "花蓮壽豐鄉公所", "requester_email": "shoufeng@gov.tw",
                "location": "花蓮縣壽豐鄉", "admin_area": "花蓮縣壽豐鄉", "lat": 23.871, "lon": 121.508,
                "resource_type": "有形資源", "category": "重型機具", "item": "抽水機", "qty": 5, "urgency": 5,
                "verification_status": VERIFIED, "verified_by": "花蓮壽豐鄉公所", "blue_check": True,
                "status": "未處理", "matched_provider": "", "raw_text": "壽豐中山路急需大型抽水機。"
            },
            {
                "id": "D002", "time": (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"),
                "source": "民眾通報", "requester": "翠華村居民", "requester_email": "resident@example.com",
                "location": "南投縣仁愛鄉翠華村", "admin_area": "南投縣仁愛鄉", "lat": 24.025, "lon": 121.128,
                "resource_type": "有形資源", "category": "飲用水", "item": "礦泉水", "qty": 100, "urgency": 4,
                "verification_status": PENDING, "verified_by": "待南投縣仁愛鄉地方單位確認", "blue_check": False,
                "status": "未處理", "matched_provider": "", "raw_text": "仁愛鄉翠華村聯外道路中斷，急需礦泉水支援。"
            },
            {
                "id": "D003", "time": (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"),
                "source": "民眾通報", "requester": "壽豐居民王小姐", "requester_email": "resident@example.com",
                "location": "花蓮縣壽豐鄉豐山村", "admin_area": "花蓮縣壽豐鄉", "lat": 23.850, "lon": 121.500,
                "resource_type": "金流資源", "category": "物資採購金", "item": "臨時安置採購金", "qty": 30000, "urgency": 3,
                "verification_status": PENDING, "verified_by": "待花蓮縣壽豐鄉公所確認", "blue_check": False,
                "status": "未處理", "matched_provider": "", "raw_text": "家裡淹水需要臨時採購生活用品與安置費用。"
            }
        ]

    if "supplies" not in st.session_state:
        st.session_state.supplies = [
            {
                "id": "S001", "owner_user_id": "U002", "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
                "source": "企業表單", "provider": "統一企業", "provider_email": "csr@example.com",
                "location_current": "台南市永康區", "lat": 23.026, "lon": 120.254,
                "resource_type": "有形資源", "category": "飲用水", "item": "礦泉水", "qty": 500,
                "verification_status": PENDING, "blue_check": False, "status": "可調派",
                "raw_text": "本公司願捐贈500箱礦泉水，存放於永康物流中心。"
            },
            {
                "id": "S002", "owner_user_id": "U002", "time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
                "source": "志工表單", "provider": "吉普車救援隊", "provider_email": "jeep@example.com",
                "location_current": "花蓮市區", "lat": 23.987, "lon": 121.601,
                "resource_type": "有形資源", "category": "重型機具", "item": "四輪傳動車與抽水機", "qty": 3,
                "verification_status": UNVERIFIED, "blue_check": False, "status": "可調派",
                "raw_text": "花蓮在地車隊備有3台抽水機可支援涉水。"
            },
            {
                "id": "S003", "owner_user_id": "U001", "time": (now - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M"),
                "source": "政府備援庫存", "provider": "花蓮縣政府消防局", "provider_email": "fire@gov.tw",
                "location_current": "花蓮市", "lat": 23.991, "lon": 121.620,
                "resource_type": "無形資源", "category": "人力", "item": "救災人力", "qty": 20,
                "verification_status": VERIFIED, "blue_check": True, "status": "可調派",
                "raw_text": "可支援20名消防救災人力。"
            }
        ]

    for key, default in {
        "claim_requests": [], "dispatch_records": [], "notifications": [], "email_logs": [],
        "chat_history": [{"role": "assistant", "content": "您好！請說明所在地與需求，或說明您可提供的物資/人力/捐款。"}]
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

# ============================================================
# 3. AI 解析與媒合
# ============================================================
def extract_info_with_ai(raw_text=None, image_bytes=None, mime_type="image/jpeg"):
    if not GROQ_API_KEY:
        return {"error": "尚未設定 GROQ_API_KEY"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        taxonomy_text = json.dumps(RESOURCE_TAXONOMY, ensure_ascii=False)
        system_prompt = f"""
你是一個專業防災資源調度員。請判斷輸入是 Demand 或 Supply，並輸出 JSON。
資源分類必須使用：{taxonomy_text}
格式：
{{
  "info_type": "Demand 或 Supply",
  "data": {{
    "location": "需求地點，Supply 可留空",
    "admin_area": "縣市鄉鎮區或里，例如花蓮縣壽豐鄉",
    "provider": "供給者名稱，Demand 留空",
    "location_current": "供給所在地，Demand 留空",
    "resource_type": "有形資源/無形資源/金流資源",
    "category": "分類細項",
    "item": "具體品項/服務/金額用途",
    "qty": 數量數字,
    "urgency": 緊急度1-5,
    "lat": 緯度浮點數,
    "lon": 經度浮點數
  }}
}}
只輸出 JSON。
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
        start_idx, end_idx = raw_output.find("{"), raw_output.rfind("}")
        if start_idx != -1 and end_idx != -1:
            return json.loads(raw_output[start_idx:end_idx + 1])
        return {"error": "格式異常", "raw": raw_output}
    except Exception as e:
        return {"error": str(e)}


def compute_match_score(demand, supply):
    score = 0
    reasons = []

    if demand.get("resource_type") == supply.get("resource_type"):
        score += 20
        reasons.append("資源型態一致")
    else:
        reasons.append("資源型態不一致")

    if demand.get("category") == supply.get("category"):
        score += 30
        reasons.append("分類完全一致")
    elif demand.get("item", "") and demand.get("item", "") in supply.get("item", ""):
        score += 25
        reasons.append("品項語意接近")
    elif supply.get("item", "") and supply.get("item", "") in demand.get("item", ""):
        score += 25
        reasons.append("品項語意接近")
    else:
        reasons.append("品項/分類不完全一致")

    if int(supply.get("qty", 0)) >= int(demand.get("qty", 0)):
        score += 20
        reasons.append("供給數量足夠")
    elif int(supply.get("qty", 0)) > 0:
        score += 10
        reasons.append("供給可部分支援")
    else:
        reasons.append("供給庫存不足")

    km = haversine_km(demand.get("lat"), demand.get("lon"), supply.get("lat"), supply.get("lon"))
    if km is None:
        score += 5
        reasons.append("缺少座標，距離僅作弱判斷")
    elif km <= 30:
        score += 20
        reasons.append(f"距離近：約 {km:.1f} km")
    elif km <= 150:
        score += 12
        reasons.append(f"距離中等：約 {km:.1f} km")
    else:
        score += 5
        reasons.append(f"距離較遠：約 {km:.1f} km")

    if demand.get("verification_status") == VERIFIED:
        score += 5
        reasons.append("需求已認證")
    if supply.get("verification_status") == VERIFIED:
        score += 5
        reasons.append("供給已認證")

    return min(score, 100), "；".join(reasons)


def ai_match_resources(target_demand, available_supplies, trusted_only=False):
    supplies = [s for s in available_supplies if s.get("qty", 0) > 0]
    if trusted_only:
        supplies = [s for s in supplies if s.get("verification_status") == VERIFIED]
    if not supplies:
        return []

    # 沒有 API key 時，使用本地規則媒合，方便 Demo 穩定執行。
    if not GROQ_API_KEY:
        results = []
        for s in supplies:
            score, reason = compute_match_score(target_demand, s)
            if score >= 35:
                results.append({"supply_id": s["id"], "match_score": score, "reason": reason})
        return sorted(results, key=lambda x: x["match_score"], reverse=True)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        prompt = f"""
你是一個防災資源調度 AI 系統。請依據地理距離、資源型態、分類、品項語意、數量、認證狀態排序。
需求：{json.dumps(target_demand, ensure_ascii=False)}
供給：{json.dumps(supplies, ensure_ascii=False)}
輸出 JSON 陣列，每筆包含 supply_id, match_score, reason。只輸出 JSON 陣列。
"""
        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        raw_output = res.choices[0].message.content
        start_idx, end_idx = raw_output.find("["), raw_output.rfind("]")
        if start_idx != -1 and end_idx != -1:
            return json.loads(raw_output[start_idx:end_idx + 1])
        return [{"error": "解析失敗", "raw": raw_output}]
    except Exception as e:
        # API 失敗時也用本地規則 fallback
        results = []
        for s in supplies:
            score, reason = compute_match_score(target_demand, s)
            results.append({"supply_id": s["id"], "match_score": score, "reason": reason + f"；AI fallback：{e}"})
        return sorted(results, key=lambda x: x["match_score"], reverse=True)

# ============================================================
# 4. 正規化與資料建立
# ============================================================
def normalize_record(record, is_demand=True):
    user = st.session_state.current_user or {}
    category = record.get("category") or "生活用品"
    record.setdefault("resource_type", guess_resource_type(category))
    record.setdefault("category", category)
    record.setdefault("qty", 1)
    record.setdefault("urgency", 3)
    record.setdefault("admin_area", record.get("location", user.get("area", "")))
    record.setdefault("verification_status", user.get("verification_status", UNVERIFIED))
    record.setdefault("blue_check", user.get("blue_check", False))

    if is_demand:
        record.setdefault("requester", user.get("name", "一般民眾"))
        record.setdefault("requester_email", user.get("email", ""))
        record.setdefault("matched_provider", "")
        if user.get("role") == "政府單位" and user.get("blue_check"):
            record["verification_status"] = VERIFIED
            record["blue_check"] = True
            record["verified_by"] = user.get("name", "政府單位")
        else:
            record["verification_status"] = PENDING
            record["blue_check"] = False
            record["verified_by"] = f"待 {record.get('admin_area', record.get('location', '地方單位'))} 政府單位確認"
    else:
        record.setdefault("provider", user.get("name", "供給方"))
        record.setdefault("provider_email", user.get("email", ""))
        record.setdefault("owner_user_id", user.get("user_id", ""))
        if "location" in record and not record.get("location_current"):
            record["location_current"] = record["location"]
    return record


def apply_dispatch(demand_id, supply_id, qty, mode="AI調度", claim_id=None):
    demand = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    supply = next((s for s in st.session_state.supplies if s["id"] == supply_id), None)
    if not demand or not supply:
        return False, "找不到需求或供給資料。"

    qty = min(int(qty), int(demand.get("qty", 0)), int(supply.get("qty", 0)))
    if qty <= 0:
        return False, "可調度數量不足。"

    demand["qty"] -= qty
    supply["qty"] -= qty
    provider_name = supply.get("provider", "供給方")

    if demand.get("matched_provider"):
        demand["matched_provider"] += f", {provider_name}({qty}件/{mode})"
    else:
        demand["matched_provider"] = f"{provider_name}({qty}件/{mode})"

    demand["status"] = "已完成配對" if demand["qty"] <= 0 else "部分配對 (尚缺)"
    supply["status"] = "已指派 (無庫存)" if supply["qty"] <= 0 else "可調派 (有剩餘)"

    record = {
        "record_id": generate_id("R"), "time": now_str(), "mode": mode,
        "demand_id": demand_id, "supply_id": supply_id,
        "provider": provider_name, "item": demand.get("item"), "qty": qty,
        "location": demand.get("location"), "claim_id": claim_id or ""
    }
    st.session_state.dispatch_records.insert(0, record)
    send_match_emails(demand, supply, qty, mode)
    add_notification(f"✅ {mode}完成：{provider_name} 支援 {qty} 件 {demand.get('item')} 至 {demand.get('location')}。", "dispatch")
    return True, f"成功調度 {qty} 件資源，並建立 Email 通知紀錄。"

# ============================================================
# 5. 認領申請：先媒合檢查，不直接認領
# ============================================================
def create_claim_request(demand_id, supply_id, claim_qty, note):
    demand = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    supply = next((s for s in st.session_state.supplies if s["id"] == supply_id), None)
    if not demand or not supply:
        return False, "找不到需求或供給資料。"

    claim_qty = min(int(claim_qty), int(demand.get("qty", 0)))
    if claim_qty <= 0:
        return False, "認領數量需大於 0。"

    score, reason = compute_match_score(demand, supply)
    enough_qty = int(supply.get("qty", 0)) >= claim_qty
    same_type = demand.get("resource_type") == supply.get("resource_type")
    same_category_or_item = (
        demand.get("category") == supply.get("category") or
        demand.get("item", "") in supply.get("item", "") or
        supply.get("item", "") in demand.get("item", "")
    )

    if not enough_qty:
        status = "❌ 媒合未通過：供給數量不足"
    elif not same_type:
        status = "❌ 媒合未通過：資源型態不一致"
    elif not same_category_or_item and score < 60:
        status = "❌ 媒合未通過：品項不相符"
    elif demand.get("verification_status") != VERIFIED:
        status = "🟡 媒合初步通過：需求待政府認證後才可調度"
    elif score >= 60:
        status = "🟢 媒合通過，待政府/平台確認調度"
    else:
        status = "🟡 媒合需人工複核"

    claim = {
        "claim_id": generate_id("C"), "time": now_str(), "demand_id": demand_id, "supply_id": supply_id,
        "provider": supply.get("provider"), "provider_email": supply.get("provider_email"),
        "item": demand.get("item"), "claim_qty": claim_qty, "demand_location": demand.get("location"),
        "demand_admin_area": demand.get("admin_area"), "demand_verification": demand.get("verification_status"),
        "match_score": score, "match_reason": reason, "status": status, "note": note,
        "approved_by": ""
    }
    st.session_state.claim_requests.insert(0, claim)
    add_notification(f"🤝 新認領申請：{supply.get('provider')} 申請支援 {claim_qty} 件 {demand.get('item')}，媒合分數 {score}。", "claim")
    return True, status


def approve_claim_request(claim_id, approver_name):
    claim = next((c for c in st.session_state.claim_requests if c["claim_id"] == claim_id), None)
    if not claim:
        return False, "找不到認領申請。"
    if not (claim["status"].startswith("🟢") or claim["status"].startswith("🟡")):
        return False, "此申請尚未通過媒合檢查，不能核准調度。"

    demand = next((d for d in st.session_state.demands if d["id"] == claim["demand_id"]), None)
    if demand and demand.get("verification_status") != VERIFIED:
        return False, "需求尚未完成政府認證，不能核准調度。"

    ok, msg = apply_dispatch(claim["demand_id"], claim["supply_id"], claim["claim_qty"], mode="認領媒合", claim_id=claim_id)
    if ok:
        claim["status"] = "✅ 已核准並完成調度"
        claim["approved_by"] = approver_name
    return ok, msg


def reject_claim_request(claim_id, approver_name):
    claim = next((c for c in st.session_state.claim_requests if c["claim_id"] == claim_id), None)
    if claim:
        claim["status"] = "❌ 已駁回"
        claim["approved_by"] = approver_name
        add_notification(f"❌ 認領申請 {claim_id} 已由 {approver_name} 駁回。", "claim")

# ============================================================
# 6. 認證審核：政府只能審核同區/里需求
# ============================================================
def verify_demand(demand_id, verifier):
    demand = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    if demand:
        demand["verification_status"] = VERIFIED
        demand["blue_check"] = True
        demand["verified_by"] = verifier.get("name", "政府單位")
        add_notification(f"✅ 需求 {demand_id} 已由 {verifier.get('name')} 認證。", "verify")


def mark_unverified(demand_id, verifier):
    demand = next((d for d in st.session_state.demands if d["id"] == demand_id), None)
    if demand:
        demand["verification_status"] = UNVERIFIED
        demand["blue_check"] = False
        demand["verified_by"] = f"{verifier.get('name')} 標記未認證"
        add_notification(f"⚪ 需求 {demand_id} 已由 {verifier.get('name')} 標記未認證。", "verify")

# ============================================================
# 7. UI：登入入口與側邊欄
# ============================================================
st.set_page_config(page_title="ResQ-Link 韌性臺灣", layout="wide", page_icon="⚖️")
init_session_state()


def login_landing_page():
    st.title("⚖️ ResQ-Link 韌性臺灣")
    st.subheader("可信任防災資源分類、認證、認領與媒合平台")
    st.info("請先選擇登入身分。不同身分會看到不同功能：政府可審核同區需求，公司/NGO 可提出供給與認領申請，一般民眾可通報需求。")

    c1, c2, c3 = st.columns(3)
    role_cards = [
        ("政府單位", "🏛️", "審核同區/里需求、核准認領媒合、管理可信資訊"),
        ("公司/NGO/志工團體", "🏢", "登錄可供給資源、提出認領申請、等待媒合確認"),
        ("一般民眾", "👤", "提出需求或提供小型支援，需求會送地方單位認證")
    ]
    for col, (role, icon, desc) in zip([c1, c2, c3], role_cards):
        with col:
            st.markdown(f"### {icon} {role}")
            st.write(desc)
            users = [u for u in st.session_state.users if u["role"] == role]
            labels = {u["user_id"]: f"{u['name']}｜{u['verification_status']}" for u in users}
            selected = st.selectbox("選擇 Demo 帳號", list(labels.keys()), format_func=lambda x: labels[x], key=f"login_{role}")
            if st.button(f"以{role}登入", key=f"btn_{role}", type="primary" if role == "政府單位" else "secondary"):
                st.session_state.current_user = next(u for u in st.session_state.users if u["user_id"] == selected)
                st.rerun()

    st.divider()
    with st.expander("沒有帳號？快速註冊"):
        role = st.selectbox("身分角色", ROLE_OPTIONS)
        name = st.text_input("姓名 / 單位顯示名稱")
        email = st.text_input("Email（政府單位建議使用 gov.tw 公務信箱）")
        phone = st.text_input("聯絡電話")
        area = st.text_input("服務/所在行政區或里", placeholder="例如：花蓮縣壽豐鄉 / 花蓮縣壽豐鄉豐山村")
        org = st.text_input("所屬單位 / 組織")
        title = st.text_input("職稱", placeholder="例如：里長、承辦人、CSR窗口")
        uploaded_doc = st.file_uploader("證明文件（Demo 可選）：名片、公文、單位證明", type=["pdf", "png", "jpg", "jpeg"])
        if st.button("建立並登入帳號"):
            if role == "政府單位" and is_gov_email(email):
                verification_status, blue_check = VERIFIED, True
            elif role == "政府單位" and uploaded_doc is not None:
                verification_status, blue_check = PENDING, False
            elif role == "公司/NGO/志工團體":
                verification_status, blue_check = PENDING, False
            else:
                verification_status, blue_check = UNVERIFIED, False
            new_user = {
                "user_id": generate_id("U"), "name": name or "未命名使用者", "role": role,
                "email": email, "phone": phone, "area": area, "org": org, "title": title,
                "verification_status": verification_status, "blue_check": blue_check, "signup_time": now_str()
            }
            st.session_state.users.append(new_user)
            st.session_state.current_user = new_user
            add_notification(f"👤 新帳號註冊：{new_user['name']}｜{verification_status}", "system")
            st.rerun()


if st.session_state.current_user is None:
    login_landing_page()
    st.stop()

user = st.session_state.current_user
with st.sidebar:
    st.title("⚖️ ResQ-Link")
    st.markdown(f"**{user.get('name')}** {'✅' if user.get('blue_check') else ''}")
    st.caption(f"{user.get('role')}｜{user.get('verification_status')}｜{user.get('area')}")
    if st.button("登出 / 回登入首頁"):
        st.session_state.current_user = None
        st.rerun()

    base_pages = ["🏠 平台總覽", "➕ 新增需求/供給", "📊 戰備資源池", "📋 公開需求牆", "🤖 AI 調配引擎", "🤝 認領媒合審核", "📧 Email 通知紀錄"]
    if user.get("role") == "政府單位":
        pages = ["🏠 平台總覽", "✅ 同區需求認證中心", "🤝 認領媒合審核", "📊 戰備資源池", "📋 公開需求牆", "🤖 AI 調配引擎", "➕ 新增需求/供給", "📧 Email 通知紀錄", "👥 帳號清單"]
    elif user.get("role") == "公司/NGO/志工團體":
        pages = ["🏠 平台總覽", "➕ 新增需求/供給", "📋 公開需求牆", "🤝 認領媒合審核", "📊 戰備資源池", "📧 Email 通知紀錄"]
    else:
        pages = ["🏠 平台總覽", "➕ 新增需求/供給", "📋 公開需求牆", "📊 戰備資源池", "📧 Email 通知紀錄"]
    page = st.radio("功能分頁", pages)

    st.divider()
    st.subheader("🔔 通知")
    for notif in st.session_state.notifications[:5]:
        st.markdown(f"<div style='border-left:4px solid #3182ce; padding-left:8px; margin-bottom:8px; font-size:0.85em;'><b>{notif['time']}</b><br>{notif['msg']}</div>", unsafe_allow_html=True)
    if not st.session_state.notifications:
        st.caption("目前無通知。")

# ============================================================
# 8. 分頁：平台總覽
# ============================================================
if page == "🏠 平台總覽":
    st.title("🏠 平台總覽")
    st.markdown("""
    本版將流程拆成正式平台分頁：
    1. **登入分流**：政府單位、公司/NGO、一般民眾入口分開。
    2. **同區認證**：政府只能審核自己服務行政區/里的民眾需求。
    3. **認領不等於配對**：供給方只能提出認領申請，系統會先做資源媒合檢查。
    4. **媒合通過後才調度**：確認需求已認證、供給有庫存且品項相符後，才扣庫存並寄 Email。
    """)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("待處理需求", len([d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"]]))
    c2.metric("待政府認證", len([d for d in st.session_state.demands if d.get("verification_status") == PENDING]))
    c3.metric("可調派供給", len([s for s in st.session_state.supplies if s.get("qty", 0) > 0]))
    c4.metric("認領申請", len(st.session_state.claim_requests))

    st.subheader("目前角色可做的事")
    if user.get("role") == "政府單位":
        st.success("你是政府單位：可審核同區需求、核准通過媒合的認領申請、進行 AI 調度。")
    elif user.get("role") == "公司/NGO/志工團體":
        st.success("你是供給方：可新增供給、在公開需求牆提出認領申請，但需通過媒合與審核後才成立。")
    else:
        st.success("你是一般民眾：可提出需求，系統會送到同區政府單位審核；也可查看公開需求。")

# ============================================================
# 9. 分頁：新增需求/供給
# ============================================================
elif page == "➕ 新增需求/供給":
    st.title("➕ 新增需求 / 供給")
    tab_manual, tab_ai = st.tabs(["手動表單", "AI 文字/圖片解析"])

    with tab_manual:
        kind = st.radio("我要新增", ["需求 Demand", "供給 Supply"], horizontal=True)
        is_demand = kind.startswith("需求")
        with st.form("manual_form"):
            resource_type = st.selectbox("資源型態", list(RESOURCE_TAXONOMY.keys()))
            category = st.selectbox("資源分類", RESOURCE_TAXONOMY[resource_type])
            item = st.text_input("具體項目", value="礦泉水" if category == "飲用水" else "")
            qty = st.number_input("數量", min_value=1, value=10)
            urgency = st.slider("緊急程度", 1, 5, 3)
            if is_demand:
                location = st.text_input("需求地點", value=user.get("area", ""))
                admin_area = st.text_input("行政區/里（用於政府同區審核）", value=user.get("area", ""))
            else:
                location = st.text_input("供給目前所在地", value=user.get("area", ""))
                admin_area = user.get("area", "")
            lat = st.number_input("緯度 lat（Demo 可填）", value=23.871, format="%.6f")
            lon = st.number_input("經度 lon（Demo 可填）", value=121.508, format="%.6f")
            raw_text = st.text_area("補充說明")
            submitted = st.form_submit_button("送出")

        if submitted:
            if is_demand:
                rec = {
                    "id": generate_id("D"), "time": now_str(), "source": "手動表單",
                    "requester": user.get("name"), "requester_email": user.get("email"),
                    "location": location, "admin_area": admin_area, "lat": lat, "lon": lon,
                    "resource_type": resource_type, "category": category, "item": item, "qty": int(qty), "urgency": urgency,
                    "status": "未處理", "raw_text": raw_text
                }
                st.session_state.demands.append(normalize_record(rec, True))
                st.success("需求已建立。若你不是已認證政府單位，此需求會進入待認證。")
            else:
                rec = {
                    "id": generate_id("S"), "owner_user_id": user.get("user_id"), "time": now_str(), "source": "手動表單",
                    "provider": user.get("name"), "provider_email": user.get("email"),
                    "location_current": location, "lat": lat, "lon": lon,
                    "resource_type": resource_type, "category": category, "item": item, "qty": int(qty),
                    "verification_status": user.get("verification_status", UNVERIFIED), "blue_check": user.get("blue_check", False),
                    "status": "可調派", "raw_text": raw_text
                }
                st.session_state.supplies.append(normalize_record(rec, False))
                st.success("供給已建立，可到公開需求牆提出認領申請。")
            st.rerun()

    with tab_ai:
        uploaded_file = st.file_uploader("上傳照片（可選）", type=["jpg", "jpeg", "png"])
        raw_text = st.text_area("輸入文字", placeholder="例如：我是花蓮壽豐居民，需要 5 台抽水機")
        if st.button("AI 解析並寫入"):
            img_bytes = uploaded_file.getvalue() if uploaded_file else None
            mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
            result = extract_info_with_ai(raw_text or "請根據圖片判斷", img_bytes, mime_type)
            if "error" in result:
                st.error(result["error"])
            else:
                data = result.get("data", result)
                is_demand = "demand" in result.get("info_type", "").lower()
                rec = {
                    "id": generate_id("D" if is_demand else "S"), "time": now_str(), "source": "AI解析",
                    "status": "未處理" if is_demand else "可調派", "raw_text": raw_text
                }
                rec.update(data)
                rec = normalize_record(rec, is_demand)
                if is_demand:
                    st.session_state.demands.append(rec)
                else:
                    st.session_state.supplies.append(rec)
                st.success("已寫入資料庫")
                st.json(result)

# ============================================================
# 10. 分頁：政府同區認證中心
# ============================================================
elif page == "✅ 同區需求認證中心":
    st.title("✅ 同區需求認證中心")
    if user.get("role") != "政府單位" or not user.get("blue_check"):
        st.warning("只有已認證政府單位適合使用此頁。政府單位需公務信箱或人工審核取得藍勾勾。")

    gov_area = user.get("area", "")
    st.info(f"目前政府服務區域：{gov_area}。系統只顯示行政區/位置與此區域相符的民眾需求。")
    pending_same_area = [
        d for d in st.session_state.demands
        if d.get("verification_status") in [PENDING, UNVERIFIED]
        and same_admin_area(gov_area, d.get("admin_area") or d.get("location"))
    ]
    other_pending = [d for d in st.session_state.demands if d.get("verification_status") in [PENDING, UNVERIFIED] and d not in pending_same_area]

    st.subheader("可審核：同區/同里需求")
    if not pending_same_area:
        st.success("目前沒有你所屬行政區可審核的需求。")
    for d in pending_same_area:
        with st.container(border=True):
            st.markdown(f"### {d.get('id')}｜{d.get('item')} x {d.get('qty')}｜{d.get('location')}")
            st.write(f"行政區：{d.get('admin_area')}｜通報者：{d.get('requester')}｜Email：{d.get('requester_email')}")
            st.write(f"分類：{d.get('resource_type')} / {d.get('category')}｜緊急程度：{d.get('urgency')}")
            st.caption(f"原文：{d.get('raw_text')}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 通過認證，給藍勾勾", key=f"verify_{d['id']}"):
                    verify_demand(d["id"], user)
                    st.rerun()
            with c2:
                if st.button("⚪ 標記未認證", key=f"unverify_{d['id']}"):
                    mark_unverified(d["id"], user)
                    st.rerun()

    with st.expander("其他區域待認證需求（只能查看，不能審核）"):
        if other_pending:
            st.dataframe(pd.DataFrame(other_pending), hide_index=True, use_container_width=True)
        else:
            st.caption("無其他區域待認證需求。")

# ============================================================
# 11. 分頁：戰備資源池
# ============================================================
elif page == "📊 戰備資源池":
    st.title("📊 戰備資源池")
    filter_type = st.selectbox("依資源型態篩選", ["全部"] + list(RESOURCE_TAXONOMY.keys()))
    trust_only = st.checkbox("只顯示已認證資料")

    map_data = []
    for d in st.session_state.demands:
        if d.get("lat") and d.get("lon"):
            map_data.append({"lat": d["lat"], "lon": d["lon"], "color": "#FF0000"})
    for s in st.session_state.supplies:
        if s.get("lat") and s.get("lon") and s.get("qty", 0) > 0:
            map_data.append({"lat": s["lat"], "lon": s["lon"], "color": "#00AA00"})
    if map_data:
        st.markdown("🔴 需求點｜🟢 供給點")
        st.map(pd.DataFrame(map_data), color="color", zoom=6, use_container_width=True)

    df_d = pd.DataFrame(st.session_state.demands)
    df_s = pd.DataFrame(st.session_state.supplies)
    if filter_type != "全部":
        df_d = df_d[df_d["resource_type"] == filter_type]
        df_s = df_s[df_s["resource_type"] == filter_type]
    if trust_only:
        df_d = df_d[df_d["verification_status"] == VERIFIED]
        df_s = df_s[df_s["verification_status"] == VERIFIED]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🚨 需求")
        cols = ["id", "location", "admin_area", "resource_type", "category", "item", "qty", "urgency", "verification_status", "verified_by", "status", "matched_provider"]
        st.dataframe(df_d[[c for c in cols if c in df_d.columns]], hide_index=True, use_container_width=True)
    with col2:
        st.subheader("📦 供給")
        cols = ["id", "provider", "location_current", "resource_type", "category", "item", "qty", "verification_status", "status"]
        st.dataframe(df_s[[c for c in cols if c in df_s.columns]], hide_index=True, use_container_width=True)

# ============================================================
# 12. 分頁：公開需求牆，認領需先媒合
# ============================================================
elif page == "📋 公開需求牆":
    st.title("📋 公開需求牆：提出認領申請，不直接完成配對")
    st.warning("新版邏輯：點認領後只會建立『認領申請』，系統會先檢查你是否有相符且足量的供給。通過媒合與審核後才會扣庫存並寄通知。")

    only_verified = st.checkbox("只看藍勾勾已認證需求", value=False)
    selected_type = st.selectbox("資源型態", ["全部"] + list(RESOURCE_TAXONOMY.keys()))
    demands = [d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    if only_verified:
        demands = [d for d in demands if d.get("verification_status") == VERIFIED]
    if selected_type != "全部":
        demands = [d for d in demands if d.get("resource_type") == selected_type]

    my_supplies = [s for s in st.session_state.supplies if s.get("owner_user_id") == user.get("user_id") and s.get("qty", 0) > 0]
    if user.get("role") == "政府單位":
        my_supplies += [s for s in st.session_state.supplies if s.get("blue_check") and s.get("qty", 0) > 0]

    if not demands:
        st.info("目前沒有符合條件的需求。")
    for d in demands:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2.2, 1, 1.4])
            with c1:
                st.markdown(f"### {d.get('item')} x {d.get('qty')}｜{d.get('location')}")
                st.write(f"分類：**{d.get('resource_type')} / {d.get('category')}**")
                st.write(f"認證：**{get_badge(d)}**｜{d.get('verified_by')}")
                st.caption(f"原始通報：{d.get('raw_text')}")
            with c2:
                st.metric("緊急程度", d.get("urgency", 3))
                st.write(f"狀態：{d.get('status')}")
            with c3:
                if user.get("role") == "一般民眾":
                    st.info("一般民眾可查看需求；若要認領，請先新增供給或以供給方身分登入。")
                elif not my_supplies:
                    st.warning("你目前沒有可用供給。請先到『新增需求/供給』建立供給資料。")
                else:
                    supply_options = {s["id"]: f"{s['id']}｜{s.get('item')}｜剩 {s.get('qty')}｜{s.get('verification_status')}" for s in my_supplies}
                    with st.form(f"claim_form_{d['id']}"):
                        supply_id = st.selectbox("選擇要用哪筆供給申請", list(supply_options.keys()), format_func=lambda x: supply_options[x])
                        claim_qty = st.number_input("申請支援數量", min_value=1, max_value=max(1, int(d.get("qty", 1))), value=1)
                        note = st.text_area("備註", placeholder="例如：今天下午可送達，需要道路資訊")
                        submitted = st.form_submit_button("🤝 提出認領申請並媒合檢查")
                    if submitted:
                        ok, msg = create_claim_request(d["id"], supply_id, claim_qty, note)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()

# ============================================================
# 13. 分頁：認領媒合審核
# ============================================================
elif page == "🤝 認領媒合審核":
    st.title("🤝 認領媒合審核")
    st.caption("所有認領申請都必須先通過媒合檢查；需求若尚未政府認證，不能核准調度。")

    claims = st.session_state.claim_requests
    if user.get("role") == "公司/NGO/志工團體":
        claims = [c for c in claims if c.get("provider_email") == user.get("email")]
    elif user.get("role") == "政府單位":
        claims = [c for c in claims if same_admin_area(user.get("area"), c.get("demand_admin_area") or c.get("demand_location"))]

    if not claims:
        st.info("目前沒有可查看的認領申請。")
    for c in claims:
        demand = next((d for d in st.session_state.demands if d["id"] == c["demand_id"]), {})
        supply = next((s for s in st.session_state.supplies if s["id"] == c["supply_id"]), {})
        with st.container(border=True):
            st.markdown(f"### {c.get('claim_id')}｜{c.get('provider')} 申請支援 {c.get('claim_qty')} 件 {c.get('item')}")
            st.write(f"需求：{c.get('demand_id')}｜{c.get('demand_location')}｜需求認證：{demand.get('verification_status', c.get('demand_verification'))}")
            st.write(f"供給：{c.get('supply_id')}｜{supply.get('item')}｜剩餘庫存：{supply.get('qty')}｜供給認證：{supply.get('verification_status')}")
            st.progress(min(int(c.get("match_score", 0)), 100) / 100, text=f"媒合分數：{c.get('match_score')} 分")
            st.info(f"媒合理由：{c.get('match_reason')}")
            st.write(f"目前狀態：**{c.get('status')}**")
            if c.get("note"):
                st.caption(f"備註：{c.get('note')}")

            can_approve = user.get("role") == "政府單位" and user.get("blue_check") and same_admin_area(user.get("area"), c.get("demand_admin_area") or c.get("demand_location"))
            if can_approve and not c.get("status", "").startswith("✅") and not c.get("status", "").startswith("❌ 已駁回"):
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("✅ 核准調度：扣庫存並寄信", key=f"approve_{c['claim_id']}"):
                        ok, msg = approve_claim_request(c["claim_id"], user.get("name"))
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()
                with col_b:
                    if st.button("❌ 駁回申請", key=f"reject_{c['claim_id']}"):
                        reject_claim_request(c["claim_id"], user.get("name"))
                        st.rerun()
            elif user.get("role") == "政府單位":
                st.caption("你不是此需求行政區的政府人員，或此申請已結案，因此不能核准。")

# ============================================================
# 14. 分頁：AI 調配引擎
# ============================================================
elif page == "🤖 AI 調配引擎":
    st.title("🤖 AI 調配引擎")
    if user.get("role") != "政府單位":
        st.warning("建議由政府/指揮中心使用 AI 調配引擎。")
    pending_demands = [d for d in st.session_state.demands if d.get("status") in ["未處理", "部分配對 (尚缺)"] and d.get("qty", 0) > 0]
    if user.get("role") == "政府單位":
        pending_demands = [d for d in pending_demands if same_admin_area(user.get("area"), d.get("admin_area") or d.get("location"))]
    available_supplies = [s for s in st.session_state.supplies if s.get("qty", 0) > 0]
    trusted_only = st.checkbox("只使用已認證供給", value=False)

    if not pending_demands or not available_supplies:
        st.info("目前沒有可調度需求或可用供給。")
    else:
        options = {d["id"]: f"{d['id']}｜{d.get('location')}｜{d.get('item')} x {d.get('qty')}｜{d.get('verification_status')}" for d in pending_demands}
        selected = st.selectbox("選擇需求", list(options.keys()), format_func=lambda x: options[x])
        target = next(d for d in pending_demands if d["id"] == selected)
        st.write(f"需求認證：**{get_badge(target)}**")
        if target.get("verification_status") != VERIFIED:
            st.warning("此需求尚未認證。可以先媒合分析，但不建議直接調度。")
        if st.button("⚡ 啟動媒合分析", type="primary"):
            results = ai_match_resources(target, available_supplies, trusted_only)
            st.session_state.last_ai_results = {"demand_id": selected, "results": results}

        if st.session_state.get("last_ai_results", {}).get("demand_id") == selected:
            for r in st.session_state.last_ai_results["results"]:
                sid = r.get("supply_id")
                supply = next((s for s in available_supplies if s["id"] == sid), None)
                if not supply:
                    continue
                with st.container(border=True):
                    st.markdown(f"### {supply.get('provider')}｜{supply.get('item')}｜剩 {supply.get('qty')}")
                    st.write(f"供給認證：{get_badge(supply)}｜位置：{supply.get('location_current')}")
                    st.progress(r.get("match_score", 0) / 100, text=f"媒合分數：{r.get('match_score')} 分")
                    st.info(r.get("reason"))
                    qty = min(int(target.get("qty", 0)), int(supply.get("qty", 0)))
                    disabled = target.get("verification_status") != VERIFIED
                    if st.button("✅ 由指揮中心批准 AI 調度", key=f"dispatch_{sid}", disabled=disabled):
                        ok, msg = apply_dispatch(target["id"], sid, qty, mode="AI調度")
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()
                    if disabled:
                        st.caption("需求尚未政府認證，因此暫停直接調度。")

# ============================================================
# 15. Email / 帳號清單
# ============================================================
elif page == "📧 Email 通知紀錄":
    st.title("📧 Email 通知紀錄")
    with st.expander("SMTP .env 設定範例"):
        st.code("""SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@gmail.com""")
    if st.session_state.email_logs:
        st.dataframe(pd.DataFrame(st.session_state.email_logs), hide_index=True, use_container_width=True)
        idx = st.selectbox("查看信件內容", range(len(st.session_state.email_logs)), format_func=lambda i: f"{st.session_state.email_logs[i]['time']}｜{st.session_state.email_logs[i]['to']}｜{st.session_state.email_logs[i]['subject']}")
        st.text_area("信件內容", st.session_state.email_logs[idx]["body"], height=260)
    else:
        st.info("尚無 Email 通知紀錄。")

elif page == "👥 帳號清單":
    st.title("👥 帳號清單")
    st.dataframe(pd.DataFrame(st.session_state.users), hide_index=True, use_container_width=True)
    st.subheader("調度紀錄")
    if st.session_state.dispatch_records:
        st.dataframe(pd.DataFrame(st.session_state.dispatch_records), hide_index=True, use_container_width=True)
    else:
        st.caption("尚無調度紀錄。")

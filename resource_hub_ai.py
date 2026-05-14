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
# 1. 系統初始化與狀態管理
# ==========================================
def init_session_state():
    now = datetime.now()
    if 'demands' not in st.session_state:
        st.session_state.demands = [
            {"id": "D001", "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"), "source": "Threads", "location": "花蓮縣壽豐鄉", "lat": 23.871, "lon": 121.508, "category": "重型機具", "item": "抽水機", "qty": 5, "urgency": 5, "status": "未處理", "matched_provider": "", "raw_text": "壽豐中山路這邊急需大型抽水機😭😭"},
            {"id": "D002", "time": (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"), "source": "LINE群組", "location": "南投縣仁愛鄉", "lat": 24.025, "lon": 121.128, "category": "民生物資", "item": "礦泉水", "qty": 100, "urgency": 4, "status": "未處理", "matched_provider": "", "raw_text": "仁愛鄉翠華村聯外道路中斷，急需礦泉水支援。"}
        ]
        
    if 'supplies' not in st.session_state:
        st.session_state.supplies = [
            {"id": "S001", "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"), "source": "企業信件", "provider": "統一企業", "location_current": "台南市永康區", "lat": 23.026, "lon": 120.254, "category": "民生物資", "item": "礦泉水", "qty": 500, "status": "可調派", "raw_text": "本公司願捐贈500箱礦泉水，存放於永康物流中心。"},
            {"id": "S002", "time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"), "source": "志工表單", "provider": "吉普車救援隊", "location_current": "花蓮市區", "lat": 23.987, "lon": 121.601, "category": "重型機具", "item": "四輪傳動車與抽水機", "qty": 3, "status": "可調派", "raw_text": "花蓮在地車隊備有3台抽水機可支援涉水。"}
        ]
        
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = [{"role": "assistant", "content": "您好！我是防救災通報機器人。請告訴我您目前的所在地與遭遇的情況（或能提供的物資）。"}]
        
    # 💡 新增：模擬雙向簡訊通知的資料庫
    if 'notifications' not in st.session_state:
        st.session_state.notifications = []

# 💡 大幅升級：動態庫存扣減與雙向通知邏輯
def execute_dispatch(demand_id, supply_id, provider_name):
    demand_info = next((d for d in st.session_state.demands if d['id'] == demand_id), None)
    supply_info = next((s for s in st.session_state.supplies if s['id'] == supply_id), None)
    
    if not demand_info or not supply_info: return
    
    # 計算本次可轉移的數量 (取需求與供給的最小值)
    transfer_qty = min(demand_info['qty'], supply_info['qty'])
    
    # 1. 更新需求端狀態
    demand_info['qty'] -= transfer_qty
    # 記錄是由誰提供的 (若有多個提供者，則用逗號分隔)
    if demand_info['matched_provider']:
        demand_info['matched_provider'] += f", {provider_name}({transfer_qty}件)"
    else:
        demand_info['matched_provider'] = f"{provider_name}({transfer_qty}件)"
        
    if demand_info['qty'] <= 0:
        demand_info['status'] = "已完成配對"
    else:
        demand_info['status'] = "部分配對 (尚缺)"
        
    # 2. 更新供給端狀態
    supply_info['qty'] -= transfer_qty
    if supply_info['qty'] <= 0:
        supply_info['status'] = "已指派 (無庫存)"
    else:
        supply_info['status'] = "可調派 (有剩餘)"
        
    # 3. 觸發雙向模擬通知
    time_str = datetime.now().strftime("%H:%M:%S")
    demand_loc = demand_info.get('location', '前線災區')
    item_name = demand_info.get('item', '救援物資')
    
    msg_to_demand = f"📲 **[發送至 {demand_loc} 通報人]**\n您好，指揮中心已指派【{provider_name}】運送 {transfer_qty} 件 {item_name} 前往支援，請保持通訊暢通。"
    msg_to_supply = f"📲 **[發送至 {provider_name}]**\n調度指令下達！請協助運送 {transfer_qty} 件 {item_name} 至【{demand_loc}】，感謝您的支援。"
    
    # 將最新通知插入列表最前面
    st.session_state.notifications.insert(0, {"time": time_str, "msg": msg_to_demand, "type": "demand"})
    st.session_state.notifications.insert(0, {"time": time_str, "msg": msg_to_supply, "type": "supply"})
    
    st.session_state.success_msg = f"🎉 成功調撥 {transfer_qty} 件物資！已自動發送雙向通知簡訊。"

# ==========================================
# 2. AI 引擎 A：多模態文字與影像轉譯 (Vision + Text ETL)
# ==========================================
def extract_info_with_ai(raw_text=None, image_bytes=None, mime_type="image/jpeg"):
    if not GROQ_API_KEY: return {"error": "尚未設定 GROQ_API_KEY"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        system_prompt = """
        你是一個專業防災調度員。判斷輸入是「Demand」或「Supply」，並萃取為JSON。
        {
          "info_type": "Demand 或 Supply",
          "data": {
              "location": "若是Demand填地點，Supply留空",
              "provider": "若是Supply填提供者，Demand留空",
              "location_current": "若是Supply填所在地，Demand留空",
              "category": "物資類別", "item": "具體物品", "qty": 數量, "urgency": 緊急度1-5,
              "lat": 緯度浮點數, "lon": 經度浮點數
          }
        }
        """
        messages = [{"role": "system", "content": system_prompt}]
        if image_bytes:
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            messages.append({
                "role": "user", 
                "content": [
                    {"type": "text", "text": str(raw_text)}, 
                    # 💡 將原本寫死的 image/jpeg 換成動態的 mime_type
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]
            })
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
    except Exception as e: return {"error": str(e)}

# ==========================================
# 3. AI 引擎 B：動態語意與地理媒合
# ==========================================
def ai_match_resources(target_demand, available_supplies):
    if not GROQ_API_KEY: return [{"error": "尚未設定 GROQ_API_KEY"}]
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        
        supplies_str = json.dumps(available_supplies, ensure_ascii=False, indent=2)
        demand_str = json.dumps(target_demand, ensure_ascii=False, indent=2)
        
        prompt = f"""
        你是一個防災資源調度 AI 系統。前線需求：\n{demand_str}\n\n可調派供給：\n{supplies_str}
        請依據【地理空間距離 (優先)】、【語意吻合】、【數量】進行評估。
        必須輸出 JSON 陣列 `[...]`，包含 `supply_id`, `match_score`, `reason`。
        """

        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.0 
        )
        
        raw_output = res.choices[0].message.content
        start_idx = raw_output.find('[')
        end_idx = raw_output.rfind(']')
        if start_idx != -1 and end_idx != -1:
            parsed_data = json.loads(raw_output[start_idx:end_idx+1])
            return parsed_data if isinstance(parsed_data, list) else [parsed_data]
        return [{"error": "解析失敗", "raw": raw_output}]
    except Exception as e:
        return [{"error": str(e)}]

# ==========================================
# 4. Streamlit 介面與導覽路由
# ==========================================
st.set_page_config(page_title="韌性臺灣 - 資源調配中樞", layout="wide", page_icon="⚖️")
init_session_state()

with st.sidebar:
    st.title("⚖️ 韌性臺灣")
    page = st.radio("導覽選單", ["🏠 首頁介紹", "📥 多模態轉譯 (Vision ETL)", "💬 前線對話通報 (Chatbot)", "📊 戰備資源池 (Map)", "🤖 AI 調配引擎"])
    
    # 💡 側邊欄模擬通知中心 (全域可見)
    st.divider()
    st.subheader("🔔 雙向通知監控台")
    if not st.session_state.notifications:
        st.caption("目前無最新通知。")
    else:
        # 只顯示最新 4 筆避免畫面過長
        for notif in st.session_state.notifications[:4]:
            color = "blue" if notif["type"] == "supply" else "red"
            st.markdown(f"<div style='border-left: 4px solid {color}; padding-left: 10px; margin-bottom: 10px; font-size: 0.85em;'>"
                        f"<b>{notif['time']}</b><br>{notif['msg']}</div>", unsafe_allow_html=True)
        if len(st.session_state.notifications) > 4:
            st.caption(f"...還有 {len(st.session_state.notifications) - 4} 則歷史通知")

# --- 頁面 1：首頁介紹 ---
if page == "🏠 首頁介紹":
    st.title("🏠 韌性臺灣 - 智慧資源轉譯與調配中樞")
    st.image("https://images.unsplash.com/photo-1518770660439-4636190af475?q=80&w=2070&auto=format&fit=crop", use_container_width=True)
    st.markdown("""
    ### 🎯 解決痛點：打破資訊孤島
    在重大災害發生時，民間善心物資與官方救災資源往往因為**資訊不對稱**、**通報管道破碎**（LINE、Threads、PTT 等異質平台）而發生資源錯置。
    
    ### 🧩 我們的解法：災防微服務積木元件
    我們打造了具備 **Agent 特性** 的「災防積木元件」，能無縫嵌入現有政府防救災體系：
    1. **👁️‍🗨️ 視覺與語意轉譯器**：支援圖片上傳與對話，利用多模態 AI 自動萃取 JSON 表單。
    2. **🗺️ 空間戰情室**：將破碎的資訊轉化為即時經緯度地圖，自動追蹤供需餘量。
    3. **🤖 智能調派引擎**：自動計算地理距離與物資契合度，秒級生成調度決策並觸發雙向通知！
    """)

# --- 頁面 2：多模態轉譯 (Vision ETL) ---
elif page == "📥 多模態轉譯 (Vision ETL)":
    st.title("👁️‍🗨️ 異質情資與影像轉譯 (Vision ETL)")
    col_in, col_out = st.columns(2)
    with col_in:
        uploaded_file = st.file_uploader("📸 上傳災情照片 (可選)", type=["jpg", "png", "jpeg"])
        raw_text_input = st.text_area("補充文字說明：", placeholder="例如：我們需要抽水機")
        
        if st.button("🧠 啟動多模態解析", type="primary"):
            with st.spinner("Llama-3 Vision 解析中..."):
                img_bytes = uploaded_file.getvalue() if uploaded_file else None
                # 💡 自動抓取檔案的 MIME 類型 (例如 image/png)，若無檔案則預設 image/jpeg
                mime_type = uploaded_file.type if uploaded_file else "image/jpeg"
                
                text_to_send = raw_text_input if raw_text_input else "請根據圖片判斷災情與需求。"
                
                # 💡 將 mime_type 傳遞給函數
                result = extract_info_with_ai(raw_text=text_to_send, image_bytes=img_bytes, mime_type=mime_type)
                
                if "error" in result: 
                    st.error("解析錯誤！")
                    st.code(result["error"]) # 把錯誤印出來方便後續除錯
                else:
                    extracted = result.get("data", result)
                    is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
                    
                    new_record = {
                        "id": f"{'D' if is_demand else 'S'}{int(time.time()) % 10000:04d}", 
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M"), 
                        "source": "圖片轉譯", "raw_text": text_to_send, "status": "未處理" if is_demand else "可調派"
                    }
                    if is_demand: new_record["matched_provider"] = ""
                    new_record.update(extracted)
                    
                    if not is_demand and "location" in new_record and "location_current" not in new_record:
                        new_record["location_current"] = new_record["location"]
                    
                    if is_demand: st.session_state.demands.append(new_record); st.success("✅ 已寫入需求庫。")
                    else: st.session_state.supplies.append(new_record); st.success("✅ 已寫入供給庫。")
                    with col_out: st.json(result)

# --- 頁面 3：前線對話通報 (Chatbot) ---
elif page == "💬 前線對話通報 (Chatbot)":
    st.title("💬 前線防救災 AI 對話助理")
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if user_input := st.chat_input("請輸入您的通報內容..."):
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("AI 處理中..."):
                result = extract_info_with_ai(raw_text=user_input)
                if "error" not in result:
                    extracted = result.get("data", result)
                    is_demand = "demand" in result.get("info_type", extracted.get("info_type", "")).lower()
                    new_record = {"id": f"{'D' if is_demand else 'S'}{int(time.time()) % 10000:04d}", "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "source": "對話通報", "raw_text": user_input, "status": "未處理" if is_demand else "可調派"}
                    if is_demand: new_record["matched_provider"] = ""
                    new_record.update(extracted)
                    
                    if not is_demand and "location" in new_record and "location_current" not in new_record: new_record["location_current"] = new_record["location"]
                    
                    if is_demand: st.session_state.demands.append(new_record)
                    else: st.session_state.supplies.append(new_record)
                    reply = f"✅ 收到！已為您立案。\n- **地點**：{new_record.get('location', new_record.get('location_current', '未知'))}\n- **物資**：{new_record.get('item', '未知')} x {new_record.get('qty', 1)}"
                else: reply = "抱歉，解析遇到問題，請重試。"
                
                st.markdown(reply)
                st.session_state.chat_history.append({"role": "assistant", "content": reply})

# --- 頁面 4：戰備資源池 (Geospatial Map) ---
elif page == "📊 戰備資源池 (Map)":
    st.title("🗺️ 空間戰備資源池")
    
    map_data = []
    for d in st.session_state.demands:
        if d.get('lat') and d.get('lon'): map_data.append({"lat": d['lat'], "lon": d['lon'], "color": "#FF0000"})
    for s in st.session_state.supplies:
        # 只顯示數量大於 0 且可調派的供給
        if s.get('lat') and s.get('lon') and s.get('qty', 0) > 0: map_data.append({"lat": s['lat'], "lon": s['lon'], "color": "#00FF00"})
    
    if map_data:
        st.markdown("🔴 **紅色：前線需求** ｜ 🟢 **綠色：後勤供給**")
        st.map(pd.DataFrame(map_data), color="color", zoom=6, use_container_width=True)
    
    st.divider()
    # 💡 確保 Dataframe 抓得到新加入的 provider 欄位
    df_d = pd.DataFrame(st.session_state.demands)
    if 'matched_provider' not in df_d.columns: df_d['matched_provider'] = ""
    df_s = pd.DataFrame(st.session_state.supplies)

    col_d, col_s = st.columns(2)
    with col_d:
        st.subheader("🚨 前線需求")
        st.dataframe(df_d[['id', 'location', 'item', 'qty', 'matched_provider', 'status']], hide_index=True)
    with col_s:
        st.subheader("📦 後勤供給")
        st.dataframe(df_s[['id', 'provider', 'location_current', 'item', 'qty', 'status']], hide_index=True)

# --- 頁面 5：AI 調配引擎 ---
elif page == "🤖 AI 調配引擎":
    st.title("🤖 動態 AI 地理與語意媒合")
    if "success_msg" in st.session_state:
        st.success(st.session_state.success_msg)
        del st.session_state.success_msg 

    # 💡 容許「部分配對」的需求繼續留在池子裡
    pending_demands = [d for d in st.session_state.demands if d['status'] in ['未處理', '部分配對 (尚缺)']]
    # 只抓取還有庫存的供給
    available_supplies = [s for s in st.session_state.supplies if s['qty'] > 0]

    if pending_demands and available_supplies:
        col_match_opt, col_match_act = st.columns([1, 2])
        with col_match_opt:
            demand_options = {d['id']: f"[{d['id']}] {d.get('location')} - 缺 {d.get('item')} x {d.get('qty')}" for d in pending_demands}
            selected_demand_id = st.selectbox("🎯 選擇緊急需求：", options=list(demand_options.keys()), format_func=lambda x: demand_options[x])
            target_demand = next(d for d in pending_demands if d['id'] == selected_demand_id)
            match_btn = st.button("⚡ 啟動 Llama-3 空間媒合", type="primary", use_container_width=True)

        with col_match_act:
            if match_btn:
                with st.spinner("AI 地理空間與數量演算中..."):
                    match_results = ai_match_resources(target_demand, available_supplies)
                    if not match_results or (isinstance(match_results, list) and len(match_results) > 0 and "error" in match_results[0]):
                        st.warning("⚠️ 演算失敗或目前無適合資源。")
                    else:
                        for match in match_results:
                            supply_id = match.get("supply_id")
                            supply_info = next((s for s in available_supplies if s['id'] == supply_id), None)
                            if supply_info:
                                with st.container(border=True):
                                    st.markdown(f"#### 推薦來源：{supply_info.get('provider')} ({supply_info.get('item')})")
                                    st.progress(match.get("match_score", 0) / 100, text=f"契合度：{match.get('match_score', 0)} 分")
                                    # 顯示本次預計調撥數量
                                    expected_qty = min(target_demand['qty'], supply_info['qty'])
                                    st.write(f"📍 **目前位置：** {supply_info.get('location_current')} ｜ 📦 **預計調撥數量：** {expected_qty} 件")
                                    st.info(f"💡 **AI 理由：** {match.get('reason')}")
                                    st.button("✅ 批准調度", key=f"btn_{supply_id}", on_click=execute_dispatch, args=(target_demand['id'], supply_id, supply_info.get('provider')))
    else:
        st.info("目前沒有待處理的任務，或後勤資源已經耗盡。")
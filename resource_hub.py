import streamlit as st
import pandas as pd
import random
from datetime import datetime, timedelta

# ==========================================
# 1. 建立高擬真災防假資料庫 (Mock Database)
# ==========================================
def generate_mock_data():
    # 模擬當前時間基準
    now = datetime.now()
    
    # --- 模擬前線需求 (Demands) ---
    demands_data = [
        {"id": "D001", "time": (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"), 
         "source": "Threads (災民發文)", "location": "花蓮縣壽豐鄉", "category": "重型機具", "item": "抽水機", "qty": 2, "urgency": 5,
         "raw_text": "我家這邊水淹到大腿了！壽豐中山路這邊急需大型抽水機，打119都打不通，誰能幫幫忙😭😭 #淹水 #花蓮", 
         "status": "未處理"},
        {"id": "D002", "time": (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M"), 
         "source": "LINE (里長通報群)", "location": "南投縣仁愛鄉", "category": "民生物資", "item": "礦泉水", "qty": 100, "urgency": 4,
         "raw_text": "報告指揮中心，仁愛鄉翠華村聯外道路中斷，目前村內約有50人受困，急需礦泉水與乾糧支援，請協助空投或徒步運送。", 
         "status": "處理中"},
        {"id": "D003", "time": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"), 
         "source": "官方通報系統", "location": "高雄市茂林區", "category": "醫療支援", "item": "急救人員", "qty": 3, "urgency": 5,
         "raw_text": "[系統立案] 茂林區活動中心收容所，有三名長者出現失溫與疑似心肌梗塞症狀，道路受阻，請求醫療直升機與急救人員支援。", 
         "status": "未處理"},
        {"id": "D004", "time": (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"), 
         "source": "Facebook (在地社團)", "location": "宜蘭縣大同鄉", "category": "民生物資", "item": "睡袋", "qty": 50, "urgency": 3,
         "raw_text": "大同國小目前收容了約50位撤離的鄉親，晚上氣溫下降，現有毛毯不夠，請問有沒有善心人士可以支援睡袋？", 
         "status": "未處理"},
    ]
    
    # --- 模擬民間/官方供給 (Supplies) ---
    supplies_data = [
        {"id": "S001", "time": (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"), 
         "source": "企業信件 (CSR捐贈)", "provider": "統一企業", "category": "民生物資", "item": "礦泉水", "qty": 500, "location_current": "台南市永康區", 
         "raw_text": "本公司願捐贈500箱礦泉水投入救災，目前存放於永康物流中心，車輛已備妥，隨時可配合指揮中心調度出發。",
         "status": "可調派"},
        {"id": "S002", "time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"), 
         "source": "民間表單 (志工登記)", "provider": "吉普車救援隊", "category": "重型機具", "item": "四輪傳動車與抽水機", "qty": 3, "location_current": "花蓮市區", 
         "raw_text": "我們是花蓮在地吉普車隊，備有3台改裝四輪傳動車，且車上有載小型抽水機，可以支援涉水運送物資或抽水作業。",
         "status": "可調派"},
        {"id": "S003", "time": (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"), 
         "source": "官方資源庫", "provider": "內政部物資局", "category": "民生物資", "item": "睡袋與帳篷", "qty": 200, "location_current": "新北市五股區", 
         "raw_text": "[庫存盤點回報] 五股防災倉庫目前可調度睡袋200頂、家庭帳篷50頂，等待派車指令。",
         "status": "可調派"},
        {"id": "S004", "time": (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"), 
         "source": "LINE (醫師公會)", "provider": "熱血醫師公會", "category": "醫療支援", "item": "急救人力", "qty": 5, "location_current": "高雄市區", 
         "raw_text": "我們這邊有5位急診科醫師與護理師已經準備好醫療包，隨時可以搭乘直升機或軍車進入災區支援。",
         "status": "可調派"},
    ]
    
    return pd.DataFrame(demands_data), pd.DataFrame(supplies_data)

df_demands, df_supplies = generate_mock_data()

# ==========================================
# 2. 建立 Streamlit 戰情室 UI
# ==========================================
st.set_page_config(page_title="智慧資源調配中樞", layout="wide", page_icon="⚖️")

st.title("⚖️ 韌性臺灣 - 智慧資源調配中樞 (POC 驗證)")
st.markdown("本系統模擬接收來自社群、信件、官方系統的**非結構化通報**，轉譯為標準化格式，並由 AI 進行初步供需媒合。")

# --- 區塊 1：情報匯聚與轉譯 (ETL 展示) ---
st.header("1. 異質情資匯聚與轉譯")
st.caption("展示 AI 如何將各管道的原始文字，萃取成可供調度的標準化數據。")

col_d, col_s = st.columns(2)

with col_d:
    st.subheader("🚨 前線需求通報 (Demands)")
    # 建立一個展示用的 DataFrame，強調從 Raw Text 到結構化的過程
    st.dataframe(
        df_demands[['id', 'source', 'urgency', 'location', 'item', 'qty', 'status', 'raw_text']],
        column_config={
            "urgency": st.column_config.ProgressColumn("緊急度", min_value=1, max_value=5, format="%d 級"),
            "raw_text": st.column_config.TextColumn("原始通報內容 (AI輸入源)", width="large")
        },
        hide_index=True,
        use_container_width=True
    )

with col_s:
    st.subheader("📦 後勤與民間供給 (Supplies)")
    st.dataframe(
        df_supplies[['id', 'source', 'provider', 'item', 'qty', 'location_current', 'status', 'raw_text']],
        column_config={
            "raw_text": st.column_config.TextColumn("原始通報內容 (AI輸入源)", width="large")
        },
        hide_index=True,
        use_container_width=True
    )

st.divider()

# --- 區塊 2：系統初步媒合建議 (核心亮點) ---
st.header("2. AI 初步媒合建議 (自動調配積木)")
st.caption("系統自動比對需求與供給池，計算最適合的調配方案（考量物資類別、數量與地理距離）。")

# 這裡先用寫死的假資料模擬 AI 媒合的邏輯結果，後續可以接上真實的 Groq Prompt
st.info("💡 系統偵測到 3 筆高匹配度調度方案，等待指揮官審核。")

match_col1, match_col2, match_col3 = st.columns(3)

with match_col1:
    st.container(border=True)
    st.error("🚨 媒合方案 A (緊急度：5)")
    st.markdown("**需求：** [D001] 花蓮壽豐鄉 - 抽水機 (2台)")
    st.markdown("**供給：** [S002] 吉普車救援隊 - 抽水機 (3台)")
    st.markdown("**AI 調度理由：** 供給方正好位於花蓮市區，具備四輪傳動涉水能力，地理位置極近且符合機具需求，建議立即派發。")
    if st.button("✅ 批准調度執行", key="btn1"):
        st.toast("已發送調度指令給吉普車救援隊！")

with match_col2:
    st.container(border=True)
    st.warning("⚠️ 媒合方案 B (緊急度：4)")
    st.markdown("**需求：** [D002] 南投仁愛鄉 - 礦泉水 (100箱)")
    st.markdown("**供給：** [S001] 統一企業 - 礦泉水 (500箱)")
    st.markdown("**AI 調度理由：** 企業可提供數量大於需求，建議從台南永康倉儲調撥 100 箱，並聯絡空勤總隊協助空投。")
    if st.button("✅ 批准調度執行", key="btn2"):
        st.toast("已發送物資調撥單給統一企業！")

with match_col3:
    st.container(border=True)
    st.success("🟢 媒合方案 C (緊急度：3)")
    st.markdown("**需求：** [D004] 宜蘭大同鄉 - 睡袋 (50頂)")
    st.markdown("**供給：** [S003] 五股防災倉庫 - 睡袋 (200頂)")
    st.markdown("**AI 調度理由：** 官方庫存充足，五股至宜蘭交通目前暢通，建議調派官方貨車運送 50 頂睡袋至大同國小。")
    if st.button("✅ 批准調度執行", key="btn3"):
        st.toast("已發送派車單至五股防災倉庫！")
import streamlit as st
import pandas as pd
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Bangalore Utility Dashboard", layout="wide", page_icon="⚡")

st.title("⚡ Bangalore Power & Water Cut Tracker")
st.write("Live status dashboard compiling real-time official utility notices.")

# --- Database Fetch ---
@st.cache_data(ttl=30) # Auto-refreshes cache every 30 seconds if page is reloaded
def load_live_data():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_json = os.getenv("GOOGLE_SHEETS_CREDS_JSON")
        
        if not creds_json:
            st.warning("⚠️ GOOGLE_SHEETS_CREDS_JSON missing in your settings. Showing placeholder columns:")
            return pd.DataFrame(columns=['category', 'title', 'link', 'date', 'timestamp'])
            
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet = client.open("UtilityAlerts").sheet1
        records = sheet.get_all_records()
        
        # Safe fallback structure if sheet has only headers but no data rows yet
        if not records:
            return pd.DataFrame(columns=['category', 'title', 'link', 'date', 'timestamp'])
            
        df = pd.DataFrame(records)
        
        # --- Clean Headers Dynamically ---
        df.columns = df.columns.str.lower().str.strip()
        return df
        
    except Exception as e:
        st.error(f"Failed to pull data from Google Sheets: {e}")
        return pd.DataFrame(columns=['category', 'title', 'link', 'date', 'timestamp'])

df = load_live_data()

# --- Refresh Controls ---
if st.button("🔄 Force Refresh Dashboard"):
    st.cache_data.clear()
    st.rerun()

st.markdown("---")

# --- Dashboard Data Layout Rendering ---
# --- Dashboard Data Layout Rendering ---
# --- Dashboard Data Layout Rendering ---
# --- Dashboard Data Layout Rendering ---
# --- Dashboard Data Layout Rendering ---
# --- Dashboard Data Layout Rendering ---
if 'category' in df.columns:
    
    # Sort the dataframe so the newest timestamp rows are processed first
    if 'timestamp' in df.columns and not df.empty:
        df = df.sort_values(by='timestamp', ascending=False)
        
    col1, col2 = st.columns(2)

    with col1:
        st.header("🔌 Electricity Updates")
        power_df = df[df['category'].astype(str).str.contains("POWER|power|⚡", case=False, na=False)] if not df.empty else pd.DataFrame()
        
        if not power_df.empty:
            for _, row in power_df.head(10).iterrows():
                with st.container(border=True):
                    title = str(row.get('title', 'No Title')).strip()
                    
                    # Target column 'link' directly and fall back safely if it's empty
                    link = str(row.get('link', '')).strip()
                    if not link or link == "nan" or link == "#":
                        link = "https://news.google.com"  # Clean fallback destination
                    
                    # Render small, bold, clickable link card that opens in a fresh browser tab
                    st.markdown(f"**[{title}]({link})**")
                    st.caption(f"📅 Published: {row.get('date', 'N/A')}")
        else:
            st.success("✅ No active power cuts reported currently.")

    with col2:
        st.header("💧 Water Supply Updates")
        water_df = df[df['category'].astype(str).str.contains("WATER|water|💧", case=False, na=False)] if not df.empty else pd.DataFrame()
        
        if not water_df.empty:
            for _, row in water_df.head(10).iterrows():
                with st.container(border=True):
                    title = str(row.get('title', 'No Title')).strip()
                    
                    link = str(row.get('link', '')).strip()
                    if not link or link == "nan" or link == "#":
                        link = "https://news.google.com"
                    
                    st.markdown(f"**[{title}]({link})**")
                    st.caption(f"📅 Published: {row.get('date', 'N/A')}")
        else:
            st.success("✅ No active water supply disruptions reported.")
else:
    st.info("💡 Header initialization mismatch. Please verify row 1 of your Google Sheet has headers named: category, title, link, date, timestamp.")
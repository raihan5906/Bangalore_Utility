import os
import requests
from bs4 import BeautifulSoup
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import warnings
from bs4 import XMLParsedAsHTMLWarning

# Mute the harmless XML parsed as HTML warning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Force-load environment variables safely
load_dotenv(override=True)

# Strict filtering keywords
KEYWORDS = ["cut", "supply", "interruption", "shutdown", "outage", "maintenance"]
LOCATION_KEYWORDS = ["bangalore", "bengaluru", "bescom", "bwssb"]

def get_gsheet_client():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_json = os.getenv("GOOGLE_SHEETS_CREDS_JSON")
        if not creds_json:
            print("⚠️ GOOGLE_SHEETS_CREDS_JSON missing in environment configuration.")
            return None
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ Failed to authenticate with Google Sheets: {e}")
        return None

def send_batch_email(alerts):
    load_dotenv(override=True)

    sender = os.getenv("SENDER_EMAIL", "").strip()
    receiver = os.getenv("RECEIVER_EMAIL", "").strip()
    
    raw_password = os.getenv("EMAIL_APP_PASSWORD", "")
    app_password = raw_password.replace(" ", "").strip()

    if not sender or not app_password or not receiver:
        print("⚠️ Email configuration credentials missing or incomplete.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 Bangalore Utility Digest: {len(alerts)} New Updates"
    msg["From"] = sender
    msg["To"] = receiver

    items_html = ""
    for alert in alerts:
        color = "#d9534f" if alert['category'] == "⚡ POWER" else "#0275d8"
        items_html += f"""
        <div style="margin-bottom: 15px; padding: 12px; border-left: 5px solid {color}; background-color: #f9f9f9;">
            <strong style="color: {color};">{alert['category']}</strong>
            <p style="margin: 5px 0; font-size: 15px;">{alert['title']}</p>
            <a href="{alert['link']}" style="font-size: 13px; color: #0275d8;">Read Source Notice</a>
        </div>
        """

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px;">
          <h2 style="color: #333; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px; margin-top: 0;">
            Bangalore Utility Updates Detected
          </h2>
          <p>The following new service interruptions match your tracking criteria:</p>
          {items_html}
          <p style="font-size: 11px; color: #999; margin-top: 30px;">
            Automated alert sync processed on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
          </p>
        </div>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_content, "html"))

    try:
        # Use direct SSL Port 465 to establish immediate encryption and bypass local network inspection filters
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, app_password)
            server.sendmail(sender, receiver, msg.as_string())
        print(f"🚀 Batch email notification sent successfully to {receiver}!")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print("❌ Gmail Authentication Failed!")
        print("SMTP Code:", e.smtp_code)
        try:
            print("SMTP Message:", e.smtp_error.decode())
        except Exception:
            print("SMTP Message:", e.smtp_error)
        return False
    except Exception as e:
        print(f"❌ Failed to dispatch email pipeline: {e}")
        return False

def scrape_bangalore_news():
    alerts = []
    url = "https://news.google.com/rss/search?q=Bengaluru+utility+OR+Bangalore+power+cut+OR+BESCOM+OR+BWSSB+when:7d&hl=en-IN&gl=IN&ceid=IN:en"
    
    try:
        response = requests.get(url, timeout=15)
        soup = BeautifulSoup(response.content, "xml") # Using xml parser for strict RSS trees
        items = soup.find_all("item")
        
        for item in items:
            title = item.title.text if item.title else ""
            pub_date = item.pubDate.text if item.pubDate else (item.pubdate.text if item.pubdate else str(datetime.now().date()))
            
            # --- Robust Link Extraction Layers ---
            link = ""
            if item.find('link'):
                link = item.find('link').text
            elif item.link:
                link = item.link.text
            
            # If standard elements fail, check for raw string text attributes
            if not link and 'link' in str(item):
                try:
                    link = str(item).split('<link>')[1].split('</link>')[0]
                except Exception:
                    link = ""
                    
            link = link.strip()
            title_lower = title.lower()
            
            # Cross-reference locations with issues to guarantee precise geolocation filtering
            has_location = any(loc in title_lower for loc in LOCATION_KEYWORDS)
            has_issue = any(keyword in title_lower for keyword in KEYWORDS)
            
            if has_location and has_issue:
                category = "⚡ POWER" if "power" in title_lower or "bescom" in title_lower else "💧 WATER"
                alerts.append({
                    "category": category,
                    "title": title,
                    "link": link if link else "https://news.google.com",
                    "date": pub_date
                })
                
            if len(alerts) >= 15:
                break
                
    except Exception as e:
        print(f"❌ Scraping failed: {e}")
        
    return alerts

def sync_and_alert():
    client = get_gsheet_client()
    sheet = None
    existing_titles = []

    if client:
        try:
            sheet = client.open("UtilityAlerts").sheet1
            existing_titles = sheet.col_values(2)  
        except Exception as e:
            print(f"⚠️ Google Sheet access error: {e}. Running in standalone backup mode.")

    fresh_alerts = scrape_bangalore_news()
    print(f"🔎 Found {len(fresh_alerts)} matching news items. Syncing database...")

    to_be_notified = []
    rows_to_append = [] 

    for alert in fresh_alerts:
        if alert["title"] not in existing_titles:
            # FIXED COLUMN ALIGNMENT LAYER TO MATCH SPREADSHEET HEADERS (A, B, C, D, E)
            rows_to_append.append([
                alert["category"],  # Col A
                alert["title"],     # Col B
                alert["date"],      # Col C: date
                alert["link"],      # Col D: link
                str(datetime.now()) # Col E: timestamp
            ])
            to_be_notified.append(alert)
            existing_titles.append(alert["title"])

    # Bulk-upload everything simultaneously using exactly one write metric token
    if rows_to_append and sheet:
        try:
            print(f"📊 Bulk uploading {len(rows_to_append)} rows to Google Sheets...")
            sheet.append_rows(rows_to_append)
            print("✅ Google Sheets database updated successfully!")
        except Exception as e:
            print(f"⚠️ Failed to write batch data to Google Sheets: {e}")

    if to_be_notified:
        print(f"✉️ Processing combined notification layout for {len(to_be_notified)} new alerts...")
        send_batch_email(to_be_notified)
    else:
        print("✅ No new alerts found since the last database sync cycle.")
if __name__ == "__main__":
    print("🔄 Starting Bangalore Utility tracker routine...")
    sync_and_alert()
    print("✅ Routine execution complete.")
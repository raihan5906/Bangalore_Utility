import os
import requests
from bs4 import BeautifulSoup
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from html import escape
import warnings
from bs4 import XMLParsedAsHTMLWarning


# ============================================================
# ENVIRONMENT CONFIGURATION
# ============================================================

# Force .env values to override previously defined environment variables
load_dotenv(override=True)

# Mute harmless XML/HTML parser warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


# ============================================================
# TRACKING CONFIGURATION
# ============================================================

KEYWORDS = [
    "cut",
    "supply",
    "interruption",
    "shutdown",
    "outage",
    "maintenance"
]

LOCATION_KEYWORDS = [
    "bangalore",
    "bengaluru",
    "bescom",
    "bwssb"
]

# Only process articles from the last 7 days
NEWS_LOOKBACK_DAYS = 7

# Maximum number of alerts processed per run
MAX_ALERTS = 15


# ============================================================
# GOOGLE SHEETS AUTHENTICATION
# ============================================================

def get_gsheet_client():
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds_json = os.getenv("GOOGLE_SHEETS_CREDS_JSON")

        if not creds_json:
            print(
                "⚠️ GOOGLE_SHEETS_CREDS_JSON missing in environment configuration."
            )
            return None

        creds_dict = json.loads(creds_json)

        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict,
            scope
        )

        return gspread.authorize(creds)

    except Exception as e:
        print(f"❌ Failed to authenticate with Google Sheets: {e}")
        return None


# ============================================================
# GMAIL EMAIL NOTIFICATION
# ============================================================

def send_batch_email(alerts):

    sender = os.getenv("SENDER_EMAIL", "").strip()
    receiver = os.getenv("RECEIVER_EMAIL", "").strip()

    raw_password = os.getenv("EMAIL_APP_PASSWORD", "")
    app_password = raw_password.replace(" ", "").strip()

    if not sender or not app_password or not receiver:
        print("⚠️ Email configuration credentials missing or incomplete.")
        return False

    # --------------------------------------------------------
    # Build email
    # --------------------------------------------------------

    msg = MIMEMultipart("alternative")

    msg["Subject"] = (
        f"🚨 Bangalore Utility Digest: "
        f"{len(alerts)} New Updates"
    )

    msg["From"] = sender
    msg["To"] = receiver

    items_html = ""

    for alert in alerts:

        if alert["category"] == "⚡ POWER":
            color = "#d9534f"
        else:
            color = "#0275d8"

        safe_category = escape(alert["category"])
        safe_title = escape(alert["title"])
        safe_link = escape(alert["link"], quote=True)

        items_html += f"""
        <div style="
            margin-bottom:15px;
            padding:12px;
            border-left:5px solid {color};
            background-color:#f9f9f9;
        ">

            <strong style="color:{color};">
                {safe_category}
            </strong>

            <p style="
                margin:5px 0;
                font-size:15px;
            ">
                {safe_title}
            </p>

            <a
                href="{safe_link}"
                style="
                    font-size:13px;
                    color:#0275d8;
                "
            >
                Read Source Notice
            </a>

        </div>
        """

    html_content = f"""
    <html>

      <body style="
          font-family:Arial,sans-serif;
          line-height:1.6;
          color:#333;
      ">

        <div style="
            max-width:600px;
            margin:0 auto;
            border:1px solid #e0e0e0;
            padding:20px;
            border-radius:8px;
        ">

          <h2 style="
              color:#333;
              border-bottom:2px solid #f0f0f0;
              padding-bottom:10px;
              margin-top:0;
          ">
              Bangalore Utility Updates Detected
          </h2>

          <p>
              The following new service interruptions
              match your tracking criteria:
          </p>

          {items_html}

          <p style="
              font-size:11px;
              color:#999;
              margin-top:30px;
          ">
              Automated alert sync processed on:
              {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
          </p>

        </div>

      </body>

    </html>
    """

    msg.attach(
        MIMEText(
            html_content,
            "html",
            "utf-8"
        )
    )

    # --------------------------------------------------------
    # Gmail SMTP
    #
    # Using port 587 + STARTTLS instead of port 465 SSL.
    # This is more suitable for the GitHub Actions runner.
    # --------------------------------------------------------

    try:

        print("📧 Connecting to Gmail SMTP server...")

        with smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=30
        ) as server:

            server.ehlo()

            print("🔐 Starting TLS encryption...")

            server.starttls()

            server.ehlo()

            print("🔑 Authenticating Gmail account...")

            server.login(
                sender,
                app_password
            )

            print("📨 Sending email...")

            server.sendmail(
                sender,
                receiver,
                msg.as_string()
            )

        print(
            f"🚀 Batch email notification sent successfully "
            f"to {receiver}!"
        )

        return True

    except smtplib.SMTPAuthenticationError as e:

        print("❌ Gmail Authentication Failed!")
        print("SMTP Code:", e.smtp_code)

        try:
            print(
                "SMTP Message:",
                e.smtp_error.decode()
            )
        except Exception:
            print(
                "SMTP Message:",
                e.smtp_error
            )

        return False

    except smtplib.SMTPConnectError as e:

        print(
            f"❌ Could not connect to Gmail SMTP server: {e}"
        )

        return False

    except smtplib.SMTPException as e:

        print(
            f"❌ Gmail SMTP Error: {e}"
        )

        return False

    except Exception as e:

        print(
            f"❌ Failed to dispatch email pipeline: {e}"
        )

        return False


# ============================================================
# GOOGLE NEWS SCRAPER
# ============================================================

def scrape_bangalore_news():

    alerts = []

    url = (
        "https://news.google.com/rss/search?"
        "q=Bengaluru+utility+OR+Bangalore+power+cut+OR+BESCOM+OR+BWSSB"
        "+when:7d"
        "&hl=en-IN"
        "&gl=IN"
        "&ceid=IN:en"
    )

    try:

        print("🔎 Fetching Google News RSS feed...")

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            }
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.content,
            "xml"
        )

        items = soup.find_all("item")

        # Current UTC time
        now = datetime.now(timezone.utc)

        # Oldest acceptable article
        cutoff_time = now - timedelta(
            days=NEWS_LOOKBACK_DAYS
        )

        for item in items:

            # ------------------------------------------------
            # Title
            # ------------------------------------------------

            title = ""

            if item.title:
                title = item.title.text.strip()

            if not title:
                continue

            # ------------------------------------------------
            # Publication date
            # ------------------------------------------------

            pub_date = ""

            if item.pubDate:
                pub_date = item.pubDate.text.strip()

            elif item.pubdate:
                pub_date = item.pubdate.text.strip()

            if not pub_date:
                continue

            # ------------------------------------------------
            # Parse publication date
            # ------------------------------------------------

            try:

                published_dt = parsedate_to_datetime(
                    pub_date
                )

                # Make sure the datetime is timezone-aware
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(
                        tzinfo=timezone.utc
                    )

                published_dt = published_dt.astimezone(
                    timezone.utc
                )

            except Exception:

                print(
                    f"⚠️ Could not parse publication date: "
                    f"{title}"
                )

                continue

            # ------------------------------------------------
            # Strict 7-day filter
            # ------------------------------------------------

            if published_dt < cutoff_time:

                continue

            # Ignore future-dated articles
            if published_dt > now + timedelta(minutes=5):

                continue

            # ------------------------------------------------
            # Link
            # ------------------------------------------------

            link = ""

            if item.link:
                link = item.link.text.strip()

            if not link:

                try:

                    item_text = str(item)

                    if "<link>" in item_text:
                        link = (
                            item_text
                            .split("<link>", 1)[1]
                            .split("</link>", 1)[0]
                            .strip()
                        )

                except Exception:
                    link = ""

            if not link:
                link = "https://news.google.com"

            # ------------------------------------------------
            # Keyword filtering
            # ------------------------------------------------

            title_lower = title.lower()

            has_location = any(
                location in title_lower
                for location in LOCATION_KEYWORDS
            )

            has_issue = any(
                keyword in title_lower
                for keyword in KEYWORDS
            )

            if not has_location:
                continue

            if not has_issue:
                continue

            # ------------------------------------------------
            # Category detection
            # ------------------------------------------------

            is_power = (
                "power" in title_lower
                or "bescom" in title_lower
                or "electricity" in title_lower
            )

            is_water = (
                "water" in title_lower
                or "bwssb" in title_lower
                or "water supply" in title_lower
            )

            if is_power:

                category = "⚡ POWER"

            elif is_water:

                category = "💧 WATER"

            else:

                # Don't classify unknown utility articles
                continue

            # ------------------------------------------------
            # Add alert
            # ------------------------------------------------

            alerts.append({
                "category": category,
                "title": title,
                "link": link,
                "date": pub_date
            })

            if len(alerts) >= MAX_ALERTS:
                break

    except requests.RequestException as e:

        print(
            f"❌ Google News request failed: {e}"
        )

    except Exception as e:

        print(
            f"❌ Scraping failed: {e}"
        )

    return alerts


# ============================================================
# DATABASE SYNC + ALERT PIPELINE
# ============================================================

def sync_and_alert():

    # --------------------------------------------------------
    # Connect to Google Sheets
    # --------------------------------------------------------

    client = get_gsheet_client()

    sheet = None
    existing_titles = []

    if client:

        try:

            sheet = client.open(
                "UtilityAlerts"
            ).sheet1

            # Column B contains titles
            existing_titles = sheet.col_values(2)

        except Exception as e:

            print(
                f"⚠️ Google Sheet access error: {e}. "
                f"Running in standalone backup mode."
            )

    # --------------------------------------------------------
    # Scrape latest news
    # --------------------------------------------------------

    fresh_alerts = scrape_bangalore_news()

    print(
        f"🔎 Found {len(fresh_alerts)} matching news items. "
        f"Syncing database..."
    )

    to_be_notified = []
    rows_to_append = []

    # --------------------------------------------------------
    # Find genuinely new alerts
    # --------------------------------------------------------

    for alert in fresh_alerts:

        if alert["title"] not in existing_titles:

            rows_to_append.append([
                alert["category"],      # Column A
                alert["title"],         # Column B
                alert["date"],          # Column C
                alert["link"],          # Column D
                str(datetime.now())     # Column E
            ])

            to_be_notified.append(alert)

            # Prevent duplicate alerts during this run
            existing_titles.append(
                alert["title"]
            )

    # --------------------------------------------------------
    # Update Google Sheets
    # --------------------------------------------------------

    if rows_to_append and sheet:

        try:

            print(
                f"📊 Bulk uploading "
                f"{len(rows_to_append)} rows "
                f"to Google Sheets..."
            )

            sheet.append_rows(
                rows_to_append
            )

            print(
                "✅ Google Sheets database "
                "updated successfully!"
            )

        except Exception as e:

            print(
                f"⚠️ Failed to write batch data "
                f"to Google Sheets: {e}"
            )

    # --------------------------------------------------------
    # Send combined email
    # --------------------------------------------------------

    if to_be_notified:

        print(
            f"✉️ Processing combined notification "
            f"layout for {len(to_be_notified)} "
            f"new alerts..."
        )

        email_success = send_batch_email(
            to_be_notified
        )

        if not email_success:

            print(
                "⚠️ New alerts were saved to Google Sheets, "
                "but the email notification failed."
            )

    else:

        print(
            "✅ No new alerts found since the "
            "last database sync cycle."
        )


# ============================================================
# MAIN PROGRAM
# ============================================================

if __name__ == "__main__":

    print(
        "🔄 Starting Bangalore Utility tracker routine..."
    )

    sync_and_alert()

    print(
        "✅ Routine execution complete."
    )
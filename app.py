import streamlit as st
import pandas as pd
#
import gspread
import base64
import os
from google.oauth2.service_account import Credentials
from datetime import datetime

import ssl
import os
os.environ['CURL_CA_BUNDLE'] = ''
ssl._create_default_https_context = ssl._create_unverified_context


# ─────────────────────────────────────────────
# הגדרות
# ─────────────────────────────────────────────
SHEET_ID = "1u-hBf3fI-hG16RYwt8UDG_WCPhojmVvgWF4n1DHn92Q"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"

# עמודות הטבלה
COL_NAME       = "שם המתכון"
COL_CATEGORY   = "קטגוריה"
COL_INGREDIENTS = "מצרכים"
COL_INSTRUCTIONS = "הוראות הכנה"
COL_UPLOADED_BY = "מי העלה"

COLUMNS = [COL_NAME, COL_CATEGORY, COL_INGREDIENTS, COL_INSTRUCTIONS, COL_UPLOADED_BY]

# ─────────────────────────────────────────────
# עיצוב כללי
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="📖 ספר המתכונים המשפחתי",
    page_icon="🍳",
    layout="wide",
)

st.markdown("""
<style>
    .main { background-color: #fdf6ec; }
    h1 { color: #7b3f00; font-family: 'Georgia', serif; }
    h2, h3 { color: #a0522d; }
    .recipe-card {
        background: #fff8f0;
        border: 1px solid #e8d5b7;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 2px 2px 8px rgba(0,0,0,0.05);
    }
    .recipe-title { font-size: 1.3rem; font-weight: bold; color: #7b3f00; }
    .recipe-meta  { font-size: 0.85rem; color: #888; margin-bottom: 0.5rem; }
    .chat-bubble-user {
        background: #fff3e0; border-radius: 12px; padding: 0.6rem 1rem;
        margin: 0.4rem 0; text-align: right; direction: rtl;
    }
    .chat-bubble-bot {
        background: #f0f4ff; border-radius: 12px; padding: 0.6rem 1rem;
        margin: 0.4rem 0; direction: rtl;
    }
    .stButton>button {
        background-color: #a0522d; color: white;
        border-radius: 8px; border: none;
    }
    .stButton>button:hover { background-color: #7b3f00; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# פונקציות עזר
# ─────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_recipes() -> pd.DataFrame:
    """טעינת מתכונים מ-Google Sheets (CSV ציבורי)."""
    try:
        df = pd.read_csv(SHEET_URL)
        # וידוא שכל העמודות קיימות
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[COLUMNS].fillna("")
        return df
    except Exception as e:
        st.error(f"שגיאה בטעינת הגיליון: {e}")
        return pd.DataFrame(columns=COLUMNS)


def get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.error("❌ מפתח ANTHROPIC_API_KEY לא מוגדר. הגדר אותו כ-environment variable.")
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


def get_gspread_client():
    """
    התחברות ל-Google Sheets לצורך כתיבה.
    נדרש קובץ service_account.json או משתנה סביבה GOOGLE_SERVICE_ACCOUNT_JSON.
    """
    import json
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        creds_dict = json.loads(sa_json)
    elif os.path.exists("service_account.json"):
        with open("service_account.json") as f:
            creds_dict = json.load(f)
    else:
        return None

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def recipes_to_system_prompt(df: pd.DataFrame) -> str:
    """הפיכת הטבלה לפרומפט מערכת לבוט."""
    lines = ["אתה עוזר מתכונים משפחתי חביב ומומחה. להלן כל המתכונים שבספר המשפחתי:\n"]
    for _, row in df.iterrows():
        lines.append(f"### {row[COL_NAME]} ({row[COL_CATEGORY]})")
        lines.append(f"**מצרכים:** {row[COL_INGREDIENTS]}")
        lines.append(f"**הוראות:** {row[COL_INSTRUCTIONS]}")
        if row[COL_UPLOADED_BY]:
            lines.append(f"*הועלה על ידי:* {row[COL_UPLOADED_BY]}")
        lines.append("")
    lines.append(
        "\nענה תמיד בעברית, בחום ובידידותיות. "
        "כשנשאלים על מתכון ספציפי — ציין אותו במלואו. "
        "כשמבקשים המלצה לפי מצרכים או כמות אנשים — הצע מתכונים מהרשימה בלבד."
    )
    return "\n".join(lines)


def append_row_to_sheet(row_data: list):
    """הוספת שורה ל-Google Sheets."""
    gc = get_gspread_client()
    if gc is None:
        return False, "לא נמצאו פרטי Google Service Account. לא ניתן לכתוב לגיליון."
    try:
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.get_worksheet(0)
        ws.append_row(row_data, value_input_option="USER_ENTERED")
        return True, "✅ המתכון נוסף בהצלחה לגיליון!"
    except Exception as e:
        return False, f"שגיאה בכתיבה לגיליון: {e}"


def image_to_base64(uploaded_file) -> tuple[str, str]:
    """המרת קובץ שהועלה ל-base64."""
    data = uploaded_file.read()
    b64 = base64.standard_b64encode(data).decode("utf-8")
    mime = uploaded_file.type or "image/jpeg"
    return b64, mime


def parse_recipe_from_image(b64: str, mime: str, uploader: str) -> dict | None:
    """שליחת תמונה לגוגל ופענוח המתכון"""
    import google.generativeai as genai
    
    # חיבור לגוגל באמצעות המפתח מה-Secrets
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    prompt = f"""
    תקני בפורמט הבא (ללא טקסט נוסף) JSON **אך ורק** אנא פענח את המתכון שבתמונה (כולל אם הוא בכתב יד) והחזר **אך ורק**
    {{
        "שם המתכון": "...",
        "קטגוריה": "...",
        "מצרכים": "...",
        "הוראות הכנה": "...",
        "מי העלה": "{uploader}"
    }}
    
    הנחיות:
    - קטגוריה: בחר מתוך: עיקרית, מרק, סלט, קינוח, אפייה, שתייה, אחר
    - מצרכים: רשימה מפורדת בפסיקים
    - הוראות הכנה: שלבים ברורים, מופרדים בפסיק אנכי (|) או ממוספרים
    - אם חסר מידע - כתוב "לא צוין"
    """

    try:
        # הגדרת המודל המוביל של גוגל לפענוח תמונות (Gemini 1.5 Flash)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        # הכנת התמונה עבור גוגל
        image_parts = [
            {
                "mime_type": mime,
                "data": b64
            }
        ]
        
        # שליחת הבקשה
        response = model.generate_content([prompt, image_parts[0]])
        
        import json, re
        raw = response.text.strip()
        # ניקוי תגיות ```json אם קיימות
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        return json.loads(raw)
        
    except Exception as e:
        st.error(f"שגיאה בפענוח התמונה: {e}")
        return None

# ─────────────────────────────────────────────
# טעינת נתונים
# ─────────────────────────────────────────────
df_recipes = load_recipes()

# ─────────────────────────────────────────────
# כותרת ראשית
# ─────────────────────────────────────────────
st.markdown("<h1 style='text-align:center'>📖 ספר המתכונים המשפחתי</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center; color:#888'>טעמים של בית, מדור לדור 🍽️</p>", unsafe_allow_html=True)
st.divider()

# ─────────────────────────────────────────────
# טאבים
# ─────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📚 המתכונים שלנו", "🤖 עוזר חכם", "📸 העלאת מתכון חדש"])

# ══════════════════════════════════════════════
# TAB 1 — הצגת מתכונים
# ══════════════════════════════════════════════
with tab1:
    st.subheader("המתכונים שלנו")

    col_search, col_filter = st.columns([2, 1])
    with col_search:
        search_query = st.text_input("🔍 חפש לפי שם או מצרך", placeholder="לדוגמה: עוף, שוקולד...")
    with col_filter:
        categories = ["הכל"] + sorted(df_recipes[COL_CATEGORY].unique().tolist())
        chosen_cat = st.selectbox("סנן לפי קטגוריה", categories)

    # סינון
    filtered = df_recipes.copy()
    if chosen_cat != "הכל":
        filtered = filtered[filtered[COL_CATEGORY] == chosen_cat]
    if search_query:
        mask = (
            filtered[COL_NAME].str.contains(search_query, case=False, na=False)
            | filtered[COL_INGREDIENTS].str.contains(search_query, case=False, na=False)
        )
        filtered = filtered[mask]

    st.markdown(f"**נמצאו {len(filtered)} מתכונים**")

    if filtered.empty:
        st.info("לא נמצאו מתכונים תואמים.")
    else:
        for _, row in filtered.iterrows():
            with st.expander(f"🍴 {row[COL_NAME]}  |  {row[COL_CATEGORY]}"):
                st.markdown(f"<div class='recipe-meta'>הועלה על ידי: {row[COL_UPLOADED_BY] or 'לא ידוע'}</div>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**🛒 מצרכים**")
                    ingredients = row[COL_INGREDIENTS].replace(",", "\n- ")
                    st.markdown(f"- {ingredients}")
                with c2:
                    st.markdown("**👨‍🍳 הוראות הכנה**")
                    instructions = row[COL_INSTRUCTIONS]
                    # ניסיון לפצל לשלבים
                    steps = [s.strip() for s in instructions.replace("|", "\n").split("\n") if s.strip()]
                    if len(steps) > 1:
                        for i, step in enumerate(steps, 1):
                            st.markdown(f"{i}. {step}")
                    else:
                        st.write(instructions)

    if st.button("🔄 רענן מתכונים"):
        st.cache_data.clear()
        st.rerun()

# ══════════════════════════════════════════════
# TAB 2 — צ'אטבוט
# ══════════════════════════════════════════════
with tab2:
    st.subheader("🤖 עוזר המתכונים החכם")
    st.caption("שאל אותי על מתכונים, קבל המלצות לפי מצרכים, כמות סועדים ועוד!")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    system_prompt = recipes_to_system_prompt(df_recipes)

    # הצגת היסטוריה
    for msg in st.session_state.chat_history:
        role_label = "👤 אתה" if msg["role"] == "user" else "🤖 עוזר"
        css_class = "chat-bubble-user" if msg["role"] == "user" else "chat-bubble-bot"
        st.markdown(
            f"<div class='{css_class}'><strong>{role_label}:</strong><br>{msg['content']}</div>",
            unsafe_allow_html=True,
        )

                   # הגדרת המודל לצ'אט של גוגל
        chat_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        with st.spinner("חושב..."):
            # הפיכת היסטוריית הצ'אט לפורמט שגוגל מבין
            gemini_history = []
            for m in st.session_state.chat_history[:-1]:
                role = "user" if m["role"] == "user" else "model"
                gemini_history.append({"role": role, "parts": [m["content"]]})
            
            # פתיחת שיחת צ'אט והעברת ההיסטוריה
            chat = chat_model.start_chat(history=gemini_history)
            
            # שליחת ההודעה האחרונה לקבלת תשובה
            response = chat.send_message(user_input)
            bot_reply = response.text

        st.session_state.chat_history.append({"role": "assistant", "content": bot_reply})
        st.rerun()

    if st.button("🗑️ נקה שיחה"):
        st.session_state.chat_history = []
        st.rerun()

# ══════════════════════════════════════════════
# TAB 3 — העלאת מתכון מתמונה
# ══════════════════════════════════════════════
with tab3:
    st.subheader("📸 העלאת מתכון מתמונה")
    st.caption("העלה תמונה של מתכון (גם בכתב יד!) — קלוד יפענח ויוסיף אוטומטית לספר המשפחתי")

    uploader_name = st.text_input("שמך (מי מעלה?)", placeholder="לדוגמה: סבתא רחל")
    uploaded_file = st.file_uploader("בחר תמונה", type=["jpg", "jpeg", "png", "webp", "heic"])

    if uploaded_file:
        st.image(uploaded_file, caption="התמונה שהועלתה", use_column_width=True)

        if st.button("🔍 פענח והוסף לספר המתכונים"):
            if not uploader_name.strip():
                st.warning("אנא הכנס את שמך לפני ההעלאה.")
            else:
                with st.spinner("קלוד מפענח את המתכון... ⏳"):
                    uploaded_file.seek(0)
                    b64, mime = image_to_base64(uploaded_file)
                    parsed = parse_recipe_from_image(b64, mime, uploader_name.strip())

                if parsed:
                    st.success("✅ המתכון פוענח בהצלחה!")
                    st.markdown("### תצוגה מקדימה של המתכון שזוהה:")

                    c1, c2 = st.columns(2)
                    with c1:
                        st.text_input("שם המתכון", value=parsed.get(COL_NAME, ""), key="p_name")
                        st.text_input("קטגוריה", value=parsed.get(COL_CATEGORY, ""), key="p_cat")
                        st.text_input("מי העלה", value=parsed.get(COL_UPLOADED_BY, uploader_name), key="p_uploader")
                    with c2:
                        st.text_area("מצרכים", value=parsed.get(COL_INGREDIENTS, ""), key="p_ingredients", height=120)
                        st.text_area("הוראות הכנה", value=parsed.get(COL_INSTRUCTIONS, ""), key="p_instructions", height=120)

                    if st.button("💾 שמור לספר המתכונים"):
                        row = [
                            st.session_state.get("p_name", parsed.get(COL_NAME, "")),
                            st.session_state.get("p_cat", parsed.get(COL_CATEGORY, "")),
                            st.session_state.get("p_ingredients", parsed.get(COL_INGREDIENTS, "")),
                            st.session_state.get("p_instructions", parsed.get(COL_INSTRUCTIONS, "")),
                            st.session_state.get("p_uploader", parsed.get(COL_UPLOADED_BY, uploader_name)),
                        ]
                        success, msg = append_row_to_sheet(row)
                        if success:
                            st.success(msg)
                            st.balloons()
                            st.cache_data.clear()
                        else:
                            st.error(msg)
                            st.info("💡 לשמירה אוטומטית נדרש Google Service Account. ראה הוראות בקובץ README.")

    st.divider()
    with st.expander("ℹ️ איך מגדירים כתיבה לגיליון?"):
        st.markdown("""
**לצורך הוספת מתכונים אוטומטית ל-Google Sheets נדרש:**

1. **Google Service Account:**
   - כנס ל-[Google Cloud Console](https://console.cloud.google.com/)
   - צור פרויקט חדש (או השתמש בקיים)
   - הפעל את **Google Sheets API** ו-**Google Drive API**
   - צור **Service Account** והורד קובץ JSON
   - שמור את הקובץ כ-`service_account.json` באותה תיקייה כמו `app.py`

2. **הענק הרשאות לגיליון:**
   - פתח את ה-Google Sheet שלך
   - שתף אותו עם כתובת האימייל של ה-Service Account (client_email בקובץ ה-JSON)
   - בחר הרשאת **עורך**

3. **הגדר משתני סביבה:**
   ```bash
   export ANTHROPIC_API_KEY="המפתח-שלך"
   export GOOGLE_SERVICE_ACCOUNT_JSON='תוכן-קובץ-ה-JSON'
   ```

4. **הרץ את האפליקציה:**
   ```bash
   streamlit run app.py
   ```
""")


import streamlit as st
import trafilatura
from bs4 import BeautifulSoup
import requests
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json

# --- Config ---
st.set_page_config(page_title="Web Archive Helper", page_icon="📝", layout="wide")

# --- Custom CSS for Font Size ---
st.markdown("""
    <style>
    html, body, [class*="css"]  {
        font-size: 20px !important;
    }
    .stTextInput > div > div > input {
        font-size: 20px !important;
    }
    .stTextArea > div > div > textarea {
        font-size: 18px !important;
    }
    .stButton > button {
        font-size: 20px !important;
        height: 3em !important;
    }
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        font-size: 1.25em !important; 
    }
    .stMarkdown p {
        font-size: 20px !important;
    }
    </style>
    """, unsafe_allow_html=True)


SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive']
DOC_NAME_TARGET = '퀀트 블로그 학습 (전략) 파일'

# --- Functions ---

def clean_xml_to_markdown(xml_string):
    """
    Trafilatura returns a simplified XML. We convert this to Markdown.
    Focus on p, head, list, table, graphic.
    """
    if not xml_string:
        return ""
    
    soup = BeautifulSoup(xml_string, 'xml')
    # Trafilatura XML structure is usually <doc> or <main>
    root = soup.find('doc') or soup.find('main')
    if not root:
        return ""
        
    # Rename tags for markdownify
    xml_str_mod = str(root)
    xml_str_mod = xml_str_mod.replace('<graphic', '<img').replace('</graphic>', '</img>')
    xml_str_mod = xml_str_mod.replace('<head', '<h2').replace('</head>', '</h2>')
    xml_str_mod = xml_str_mod.replace('<list', '<ul').replace('</list>', '</ul>')
    xml_str_mod = xml_str_mod.replace('<item', '<li').replace('</item>', '</li>')
    
    # Now pass to markdownify (we need to import it)
    from markdownify import markdownify
    return markdownify(xml_str_mod, heading_style="ATX")

# --- Helper Function for Cleaning & Conversion ---
def convert_html_to_md(html_str, current_url="Manual Input"):
    """
    Cleans HTML (removes Tistory junk, etc.), extracts content via Trafilatura, 
    and converts to Markdown.
    """
    soup = BeautifulSoup(html_str, 'html.parser')
    
    # --- TISTORY SPECIFIC CLEANING ---
    # 1. Remove 'Category Other Posts' (카테고리의 다른 글)
    for junk in soup.select('.another_category'):
        junk.decompose()
        
    # 2. Remove Comments (댓글)
    for junk in soup.select('.area_reply, .area_comment, .tt-reply'):
        junk.decompose()

    # 3. Remove Promotional Links (Specific Text Patterns)
    bad_texts = ["너무나도 중요한 소식", "쿠팡 파트너스 활동"]
    for element in soup.find_all(['div', 'p', 'span']):
        text = element.get_text()
        if any(bt in text for bt in bad_texts):
            if len(text) < 500: # Safety threshold
                element.decompose()

    # Check for WAF/Bot messages (post-cleaning check)
    text_check = soup.get_text().lower()
    if "verifying that you are not a robot" in text_check or "access denied" in text_check:
        return None, "Bot detection active"
        
    # Pass the CLEANED html to Trafilatura
    clean_html_str = str(soup)
    
    result = trafilatura.extract(clean_html_str, include_images=True, include_tables=True, output_format='xml')
    if not result:
        # Fallback for plain text or simple markdown extraction if Trafilatura fails on fragments
        return None, "Trafilatura extraction failed"
        
    # Get Metadata
    meta = trafilatura.extract_metadata(clean_html_str)
    title = meta.title if meta else "Untitled"
    # Reuse the existing XML to MD function
    md_content = clean_xml_to_markdown(result)
    
    final_md = f"# {title}\n\nURL: {current_url}\n\n{md_content}"
    return final_md, None


def extract_content(url):
    import cloudscraper
    scraper = cloudscraper.create_scraper()
    
    try:
        # Attempt 1: Direct Cloudscraper
        try:
            response = scraper.get(url, timeout=10)
            if response.status_code == 200:
                md, err = convert_html_to_md(response.text, url)
                if md: return md, None
        except:
            pass 

        # Attempt 2: Google Web Cache Fallback
        try:
            cache_url = f"http://webcache.googleusercontent.com/search?q=cache:{url}"
            response = scraper.get(cache_url, timeout=10)
            if response.status_code == 200:
                if "please click here" not in response.text.lower() and "redirect" not in response.text.lower():
                    md, err = convert_html_to_md(response.text, url)
                    if md: return md, None
        except:
             pass

        # Attempt 3: Jina.ai Reader
        try:
            jina_url = f"https://r.jina.ai/{url}"
            response = scraper.get(jina_url, timeout=20)
            if response.status_code == 200:
                jina_md = response.text
                if "Verifying you are not a robot" not in jina_md:
                    final_md = f"# Scraped via Jina.ai\n\nURL: {url}\n\n{jina_md}"
                    return final_md, None
        except:
            pass

        return None, "모든 방법(Direct, Google Cache, Jina.ai)이 차단되었습니다. 😭 수동 입력 탭을 이용해주세요."
        
    except Exception as e:
        return None, f"System Error: {str(e)}"

def get_google_creds():
    creds = None
    
    # 1. Try Streamlit Secrets (for Cloud)
    if "google_token" in st.secrets:
        try:
            # We assume the user pasted the content of token.json into a secret named "google_token"
            token_info = json.loads(st.secrets["google_token"])
            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
            return creds
        except Exception as e:
            st.error(f"Secrets Error: {str(e)}")
            return None

    # 2. Try Local File (for PC)
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in (ONLY LOCAL).
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except:
                creds = None
        
        if not creds:
            if os.path.exists('credentials.json'):
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())
            else:
                return None
    return creds

def append_to_doc(md_content):
    creds = get_google_creds()
    if not creds:
        return False, "인증 실패: credentials.json 파일을 프로젝트 폴더에 넣어주세요."

    try:
        service = build('docs', 'v1', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)

        # 1. Find the file
        results = drive_service.files().list(
            q=f"name = '{DOC_NAME_TARGET}' and mimeType = 'application/vnd.google-apps.document'",
            fields="nextPageToken, files(id, name)").execute()
        items = results.get('files', [])

        if not items:
            return False, f"구글 드라이브에서 '{DOC_NAME_TARGET}' 파일을 찾을 수 없습니다."
        
        doc_id = items[0]['id']

        # 2. Append content
        # Docs API insertText handles plain text suitable. Markdown formatting won't be applied automatically.
        # But we append the text content.
        # To make it slightly better, we can insert a page break before.
        
        doc = service.documents().get(documentId=doc_id).execute()
        content = doc.get('body').get('content')
        end_index = content[-1]['endIndex'] - 1
        
        text_to_insert = "\\n\\n" + "-"*20 + "\\n\\n" + md_content
        
        requests = [
            {
                'insertText': {
                    'location': {
                        'index': end_index
                    },
                    'text': text_to_insert
                }
            },
            {
                'updateTextStyle': {
                    'range': {
                        'startIndex': end_index,
                        'endIndex': end_index + len(text_to_insert)
                    },
                    'textStyle': {
                        'fontSize': {
                            'magnitude': 12, # 10pt is default, boosting to 12pt
                            'unit': 'PT'
                        }
                    },
                    'fields': 'fontSize'
                }
            }
        ]

        service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        return True, "성공적으로 추가되었습니다. (글자 크기 12pt 적용)"
        
    except Exception as e:
        return False, f"오류 발생: {str(e)}"

# ================= MAIN UI =================

st.title("🤖 Web Content Archiver to Google Drive")
st.markdown("URL을 입력하거나 내용을 직접 붙여넣어 Google Drive에 저장하세요.")

tab1, tab2 = st.tabs(["🌐 URL 자동 분석", "✍️ 수동 입력 (HTML/텍스트)"])

# --- TAB 1: Auto Scraping ---
with tab1:
    url = st.text_input("URL을 입력하세요", "")
    
    if st.button("분석 및 변환 시작") or (url and "analyzed_url" not in st.session_state and url != ""):
        if not url:
            st.warning("URL을 입력해주세요.")
        else:
            with st.spinner(f"접속 시도 중... (Jina AI & Google Cache 가동)"):
                md_content, error = extract_content(url)
                
                if md_content:
                    st.success("변환 완료!")
                    st.session_state['analyzed_md'] = md_content
                    st.session_state['analyzed_url'] = url
                else:
                    st.error(f"실패: {error}")

# --- TAB 2: Manual Input ---
with tab2:
    st.info("💡 스크래핑이 안 되는 강력한 사이트는 여기서 **HTML 소스**나 **텍스트**를 직접 붙여넣으세요.")
    manual_title_input = st.text_input("제목 (선택)", value="Manual Scraping")
    manual_content_input = st.text_area("내용 붙여넣기 (Ctrl+A -> Ctrl+C -> Ctrl+V)", height=300, placeholder="<html>...</html> 또는 본문 텍스트")
    
    if st.button("수동 변환 및 프리뷰"):
        if not manual_content_input:
            st.warning("내용을 입력해주세요.")
        else:
            with st.spinner("변환 중..."):
                # Try to detect if it's HTML
                if "<html" in manual_content_input.lower() or "<div" in manual_content_input.lower() or "<p>" in manual_content_input.lower():
                    # Treat as HTML
                    md_content, error = convert_html_to_md(manual_content_input, url="Manual Input")
                    if not md_content: # Fallback if cleaning removed everything
                        md_content = f"# {manual_title_input}\n\n{manual_content_input}" # Just raw text
                else:
                    # Treat as Plain Text
                    md_content = f"# {manual_title_input}\n\n{manual_content_input}"
                
                st.session_state['analyzed_md'] = md_content
                st.session_state['analyzed_url'] = "Manual Input"
                st.success("수동 변환 완료! 아래에서 미리보기 및 저장을 진행하세요.")

# --- Shared Result Area (Outside Tabs) ---
if 'analyzed_md' in st.session_state:
    st.divider()
    st.subheader("📝 추출된 결과 미리보기")
    
    st.text_area("Markdown Content", st.session_state['analyzed_md'], height=300)
    
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 Markdown 파일 다운로드",
            data=st.session_state['analyzed_md'],
            file_name="scraped_content.md",
            mime="text/markdown"
        )
    with col2:
        if st.button("☁️ 구글 드라이브 추가"):
            with st.spinner("구글 드라이브에 저장 중..."):
                success, msg = append_to_doc(st.session_state['analyzed_md'])
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
    
    if st.button("🔄 초기화 (다음 작업)"):
        # Clear session state
        for key in ['analyzed_md', 'analyzed_url']:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()


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
    md_output = ""
    
    # Trafilatura XML structure is usually <doc> or <main>
    # We iterate over children
    root = soup.find('doc') or soup.find('main')
    if not root:
        return ""
        
    for element in root.descendants:
        # We only process tags, but descendants includes all. 
        # Better strategy: iterate recursively or just linear pass if flat.
        # Trafilatura output is relatively flat but has nesting (lists, tables).
        # Let's use a simpler mapping strategy: direct extraction using markdownify logic wouldn't work on XML tags directly.
        pass
    
    # Alternative: Trafilatura has its own 'output_format="json"' which gives structure?
    # Or better: Trafilatura's XML is close to HTML. Let's converting XML tags to HTML tags then markdownify.
    
    # Rename tags for markdownify
    # <graphic src="..."> -> <img src="...">
    # <head> -> <h3> (or similar)
    # <p> is <p>
    # <list> is <ul>, <item> is <li>
    # <table> is <table>
    
    xml_str_mod = str(root)
    xml_str_mod = xml_str_mod.replace('<graphic', '<img').replace('</graphic>', '</img>')
    xml_str_mod = xml_str_mod.replace('<head', '<h2').replace('</head>', '</h2>')
    xml_str_mod = xml_str_mod.replace('<list', '<ul').replace('</list>', '</ul>')
    xml_str_mod = xml_str_mod.replace('<item', '<li').replace('</item>', '</li>')
    # Row/Cell mapping if needed, but trafilatura usually preserves table structure or simplifies it.
    
    # Now pass to markdownify (we need to import it)
    from markdownify import markdownify
    # Markdownify expects HTML-like soup or string
    return markdownify(xml_str_mod, heading_style="ATX")

def extract_content(url):
    import cloudscraper
    scraper = cloudscraper.create_scraper()
    
    # Helper to clean and extract
    def process_html(html_str, current_url):
        # Check for WAF/Bot messages
        text_check = BeautifulSoup(html_str, 'html.parser').get_text().lower()
        if "verifying that you are not a robot" in text_check or "access denied" in text_check:
            return None, "Bot detection active"
            
        result = trafilatura.extract(html_str, include_images=True, include_tables=True, output_format='xml')
        if not result:
            return None, "Trafilatura extraction failed"
            
        # Get Metadata
        meta = trafilatura.extract_metadata(html_str)
        title = meta.title if meta else "Untitled"
        md_content = clean_xml_to_markdown(result)
        final_md = f"# {title}\n\nURL: {current_url}\n\n{md_content}"
        return final_md, None

    try:
        # Attempt 1: Direct Cloudscraper
        try:
            response = scraper.get(url, timeout=10)
            if response.status_code == 200:
                md, err = process_html(response.text, url)
                if md: return md, None
        except:
            pass # Fail silently and try fallback

        # Attempt 2: Google Web Cache Fallback
        # This is a powerful trick for static blogs
        try:
            cache_url = f"http://webcache.googleusercontent.com/search?q=cache:{url}"
            response = scraper.get(cache_url, timeout=10)
            if response.status_code == 200:
                md, err = process_html(response.text, url)
                if md: 
                    # Cache usually adds a header "This is Google's cache...", might want to strip it?
                    # Trafilatura usually handles main content well, but let's note it.
                    return md, None
        except:
             pass

        return None, "모든 방법(Direct, Google Cache)이 차단되었습니다. 😭 해당 사이트는 스크래핑이 매우 어렵습니다."
        
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
        
        text_to_insert = "\n\n" + "-"*20 + "\n\n" + md_content
        
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

# --- UI ---

st.title("🤖 Web Content Archiver to Google Drive")
st.markdown("URL을 입력하면 내용을 추출하여 Markdown으로 변환하고, 구글 드라이브 문서에 이어붙입니다.")

url = st.text_input("URL을 입력하세요", placeholder="https://example.com/...")

if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None

if st.button("분석 및 변환 시작"):
    if url:
        with st.spinner('웹페이지 분석 & 정제 중...'):
            md_result, error = extract_content(url)
            if error:
                st.error(error)
            else:
                st.session_state.processed_data = md_result
                st.success("변환 완료!")
    else:
        st.warning("URL을 입력해주세요.")

if st.session_state.processed_data:
    st.subheader("📝 추출된 결과 미리보기")
    st.text_area("Markdown Content", st.session_state.processed_data, height=400)
    
    col1, col2 = st.columns(2)
    
    # Download Button
    file_name = "extracted_content.md"
    col1.download_button(
        label="📥 Markdown 파일 다운로드",
        data=st.session_state.processed_data,
        file_name=file_name,
        mime="text/markdown"
    )
    
    # Google Drive Append Button
    if col2.button("☁️ 구글 드라이브 추가"):
        with st.spinner('구글 드라이브에 연결 중...'):
            success, msg = append_to_doc(st.session_state.processed_data)
            if success:
                st.success(f"{msg}")
                st.balloons()
            else:
                st.error(f"{msg}")
    
    if st.button("🔄 초기화 (다음 URL)"):
        st.session_state.processed_data = None
        st.rerun()


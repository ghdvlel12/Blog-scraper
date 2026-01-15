
from google_auth_oauthlib.flow import InstalledAppFlow
import os

SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive']

def generate():
    if not os.path.exists('credentials.json'):
        print("[ERROR] credentials.json not found!")
        return

    print("Starting Google Login. Please login in the browser tab that opens...")
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    
    print("[SUCCESS] token.json created successfully.")
    print("Now copy the content of this file to Streamlit Secrets.")

if __name__ == "__main__":
    generate()

from urllib import response
from xmlrpc import client
import anthropic
import openai
from dotenv import load_dotenv
import os
from google import genai
from PIL import Image


# Load environment variables from .env file
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")

#Initialize API clients 
ant_client = anthropic.Anthropic()
openai_client = openai.OpenAI()
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
# ============================================================================
# CONFIGURATION - Change these variables to control what the script does
# ============================================================================

PDF_FILE = r"usct_pension_files/A_B/Binyard Adam Civil War Pension.pdf"
pdf_response = pdf_file = gemini_client.files.upload(file=PDF_FILE)
print(pdf_response)
print("*"*10)

response = gemini_client.models.generate_content(
    model="gemini-2.0-flash",
    contents=[pdf_file, "What is found in this document?"]
)
print(response.text)
print("*"*10)

def test_apis():
    '''
    Test both Anthropics and OpenAI APIs with a simple Hello World Prompt.
    '''
    message = ant_client.messages.create(
        max_tokens=1024,
        messages=[{
            "content": "Hello, world",
            "role": "user",
        }],
        model="claude-sonnet-4-5-20250929",
    )

    print("ANT RESPONSE:\t\t", message.content[0].text)

    openai_response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": "Hello, world"
            }
        ], 
        max_tokens=1024,
    )
    print("OPENAI RESPONSE:\t", openai_response.choices[0].message.content) 

    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash", contents="Hello, world"
    )
    print("GEMINI RESPONSE:\t", response.text)



if __name__ == "__main__":
    #test_apis()
    print("Script executed successfully.")
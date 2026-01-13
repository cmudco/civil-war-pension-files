import anthropic
import openai
from dotenv import load_dotenv
import os


# Load environment variables from .env file
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

#Initialize API clients 
ant_client = anthropic.Anthropic()
openai_client = openai.OpenAI()


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


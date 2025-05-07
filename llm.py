import os
import fitz
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = "\n".join([page.get_text() for page in doc])
    return text

def evaluate_cv_with_openai(pdf_path, question):
    cv_text = extract_text_from_pdf(pdf_path)

    # Configure OpenAI client
    client = openai.OpenAI()

    # Prepare the messages
    messages = [
        {"role": "system", "content": "You are a hiring assistant evaluating CVs."},
        {"role": "user", "content": f"""
        Please evaluate the following CV based on the question:
        "{question}"

        CV Content:
        {cv_text}

        Rate the relevance of this CV on a scale of 0 to 100 and provide a short explanation.
        """}
    ]

    # Make the API call
    response = client.chat.completions.create(
        model="gpt-4-turbo-preview",  # Using the latest GPT-4 model
        messages=messages,
        temperature=0
    )

    return response.choices[0].message.content

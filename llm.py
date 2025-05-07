import os
import fitz
import openai
import json
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
        {"role": "system", "content": """You are a hiring assistant evaluating CVs.
        You must respond with a JSON object containing the following fields:
        - rate: number between 0 and 100
        - technical_skills: array of technical skills found in the CV
        - professional_experience: array of professional experiences with company names and durations
        - education: array of educational background
        - general_comment: string with your overall assessment
        Format your response as a valid JSON object."""},
        {"role": "user", "content": f"""
        Please evaluate the following CV based on the question:
        "{question}"

        CV Content:
        {cv_text}

        Provide your evaluation in the following JSON format:
        {{
            "rate": <number between 0 and 100>,
            "technical_skills": ["skill1", "skill2", ...],
            "professional_experience": [
                {{
                    "company": "company name",
                    "duration": "duration",
                    "role": "job title"
                }},
                ...
            ],
            "education": [
                {{
                    "degree": "degree name",
                    "institution": "school name",
                    "year": "graduation year"
                }},
                ...
            ],
            "general_comment": "your overall assessment"
        }}
        """}
    ]

    # Make the API call
    response = client.chat.completions.create(
        model="gpt-4-turbo-preview",
        messages=messages,
        temperature=0,
        response_format={ "type": "json_object" }  # Force JSON response
    )

    # Parse the JSON response
    try:
        evaluation = json.loads(response.choices[0].message.content)
        return evaluation
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}")
        return {
            "rate": 0,
            "technical_skills": [],
            "professional_experience": [],
            "education": [],
            "general_comment": "Error evaluating CV"
        }

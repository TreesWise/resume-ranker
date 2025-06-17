import json
from openai import AzureOpenAI
from dotenv import load_dotenv
import os
load_dotenv()



AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION")


def get_relevance_score(resume_text, jd_text, criteria_list):
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=OPENAI_API_VERSION,
    )

    messages = [
        {
            "role": "user",
            "content": f"Please evaluate the following resume against the job description based on these criteria: {', '.join(criteria_list)}.\n\nResume:\n{resume_text}\n\nJob Description:\n{jd_text}\n\nPlease return a score for each criterion with an explanation."    
        }
    ]

    # Build dynamic schema
    criteria_properties = {
        criterion: {
            "type": "object",
            "properties": {
                "score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": f"Score for: {criterion}. The score represents how well the resume matches this criterion."
                },
                "comment": {
                    "type": "string",
                    "description": f"Explanation for: {criterion}. Please provide a detailed explanation of how the resume meets or fails to meet this criterion."
                }
            },
            "required": ["score", "comment"]
        } for criterion in criteria_list
    }

    criteria_properties["summary_comment"] = {
        "type": "string",
        "description": "Overall candidate match summary."
    }

    function_schema = {
        "name": "evaluate_resume",
        "description": "Evaluate a resume against the job description based on user-defined criteria.",
        "parameters": {
            "type": "object",
            "properties": criteria_properties,
            "required": list(criteria_list) + ["summary_comment"]
        }
    }

    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT_NAME,
        messages=messages,
        functions=[function_schema],
        function_call={"name": "evaluate_resume"},
        temperature=0,
    )

    args_json = response.choices[0].message.function_call.arguments
    result = json.loads(args_json)
    return result

# import json
# from openai import AzureOpenAI
# from dotenv import load_dotenv
# import os
# load_dotenv()



# AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
# AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
# AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
# OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION")


# def get_relevance_score(resume_text, jd_text, criteria_list):
#     client = AzureOpenAI(
#         azure_endpoint=AZURE_OPENAI_ENDPOINT,
#         api_key=AZURE_OPENAI_API_KEY,
#         api_version=OPENAI_API_VERSION,
#     )

#     messages = [
#         {
#             "role": "user",
#             "content": f"Please evaluate the following resume against the job description based on these criteria: {', '.join(criteria_list)}.\n\nResume:\n{resume_text}\n\nJob Description:\n{jd_text}\n\nPlease return a score for each criterion with an explanation."    
#         }
#     ]

#     # Build dynamic schema
#     criteria_properties = {
#         criterion: {
#             "type": "object",
#             "properties": {
#                 "score": {
#                     "type": "integer",
#                     "minimum": 0,
#                     "maximum": 100,
#                     "description": f"Score for: {criterion}. The score represents how well the resume matches this criterion."
#                 },
#                 "comment": {
#                     "type": "string",
#                     "description": f"Explanation for: {criterion}. Please provide a detailed explanation of how the resume meets or fails to meet this criterion."
#                 }
#             },
#             "required": ["score", "comment"]
#         } for criterion in criteria_list
#     }

#     criteria_properties["summary_comment"] = {
#         "type": "string",
#         "description": "Overall candidate match summary."
#     }

#     function_schema = {
#         "name": "evaluate_resume",
#         "description": "Evaluate a resume against the job description based on user-defined criteria.",
#         "parameters": {
#             "type": "object",
#             "properties": criteria_properties,
#             "required": list(criteria_list) + ["summary_comment"]
#         }
#     }

#     response = client.chat.completions.create(
#         model=AZURE_OPENAI_DEPLOYMENT_NAME,
#         messages=messages,
#         functions=[function_schema],
#         function_call={"name": "evaluate_resume"},
#         temperature=0,
#     )

#     args_json = response.choices[0].message.function_call.arguments
#     result = json.loads(args_json)
#     return result


import json
from openai import AzureOpenAI
from dotenv import load_dotenv
import os

# Load environment variables
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

    # Compose the system/user message
    messages = [
        {
            "role": "user",
            "content": f"""You are a strict evaluator assessing a resume against a job description based on the following criteria: {', '.join(criteria_list)}.

            Assign each criterion a score from [0, 5, 10, ..., 100]. Use this guide:
            - 90–100: Excellent alignment with clear, strong evidence.
            - 70–85: Good alignment with examples or relevant experience.
            - 50–65: Some alignment, may lack depth or relevance.
            - 0–45: Weak or no alignment.

            Avoid being generous. Penalize vague phrases or lack of specifics.

Resume:
{resume_text}

Job Description:
{jd_text}

Return a JSON object with:
- For each criterion: a score (0–100) and a brief explanation.
- A 'summary_comment' with an overall evaluation."""
        }
    ]

    # Build dynamic JSON schema for OpenAI function
    criteria_properties = {
        criterion: {
            "type": "object",
            "properties": {
                "score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": f"Score for: {criterion}"
                },
                "comment": {
                    "type": "string",
                    "description": f"Explanation for: {criterion}"
                }
            },
            "required": ["score", "comment"]
        } for criterion in criteria_list
    }

    criteria_properties["summary_comment"] = {
        "type": "string",
        "description": "Overall summary of how the resume matches the JD"
    }

    function_schema = {
        "name": "evaluate_resume",
        "description": "Evaluate a resume against the job description using criteria.",
        "parameters": {
            "type": "object",
            "properties": criteria_properties,
            "required": list(criteria_list) + ["summary_comment"]
        }
    }

    # Call OpenAI chat with function schema
    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT_NAME,
        messages=messages,
        functions=[function_schema],
        function_call={"name": "evaluate_resume"},
        temperature=0,
    )

    # Parse function response JSON
    args_json = response.choices[0].message.function_call.arguments
    result = json.loads(args_json)

    return result

# def calculate_weighted_score_manual(evaluation_result, criteria_with_weights):
#     total_weight = sum(item["weight"] for item in criteria_with_weights)
#     total_weighted_score = 0
#     weight_map = {}

#     for item in criteria_with_weights:
#         criterion = item["criterion"]
#         weight = item["weight"]
#         score = evaluation_result[criterion]["score"]
#         total_weighted_score += score * weight
#         weight_map[criterion] = weight

#     # Weighted average normalized back to 0–100 scale, then scaled to 10
#     final_score = round((total_weighted_score / total_weight) / 10, 2)  # Out of 10
#     return final_score, weight_map



def calculate_weighted_score_manual(evaluation_result, criteria_with_weights):
    criteria = [item["criterion"] for item in criteria_with_weights]
    n = len(criteria)
    descending_weights = list(range(n, 0, -1))
    total_weight = sum(descending_weights)

    total_weighted_score = 0
    weight_map = {}

    for i, criterion in enumerate(criteria):
        weight = descending_weights[i]
        score = evaluation_result[criterion]["score"]
        total_weighted_score += score * weight
        weight_map[criterion] = weight

    final_score = round((total_weighted_score / total_weight) / 10, 2)
    return final_score, weight_map


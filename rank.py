
# import json
# from openai import AzureOpenAI
# from dotenv import load_dotenv
# import os
# import html

# # Load environment variables
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

#     # Compose the system/user message
#     messages = [
#         {
#             "role": "user",
#             "content": f"""You are a strict evaluator assessing a resume against a job description based on the following criteria: {', '.join(criteria_list)}.

#             Assign each criterion a score from [0,1,2 ..., 100]. Use this guide:
#             - 90–100: Excellent alignment with clear, strong evidence.
#             - 70–89: Good alignment with examples or relevant experience.
#             - 50–69: Some alignment, may lack depth or relevance.
#             - 0–49: Weak or no alignment.

#             Avoid being generous. Penalize vague phrases or lack of specifics.

# Resume:
# {resume_text}

# Job Description:
# {jd_text}

# Return a JSON object with:
# - For each criterion: a score (0–100) and a brief explanation.
# - A 'summary_comment' with an overall evaluation.""" 
#         }
#     ]

#     # Build dynamic JSON schema for OpenAI function
#     criteria_properties = {
#         criterion: {
#             "type": "object",
#             "properties": {
#                 "score": {
#                     "type": "integer",
#                     "minimum": 0,
#                     "maximum": 100,
#                     "description": f"Score for: {criterion}"
#                 },
#                 "comment": {
#                     "type": "string",
#                     "description": f"Explanation for: {criterion}"
#                 }
#             },
#             "required": ["score", "comment"]
#         } for criterion in criteria_list  # Pass original criteria, including .net
#     }

#     criteria_properties["summary_comment"] = {
#         "type": "string",
#         "description": "Overall summary of how the resume matches the JD"
#     }

#     function_schema = {
#         "name": "evaluate_resume",
#         "description": "Evaluate a resume against the job description using criteria.",
#         "parameters": {
#             "type": "object",
#             "properties": criteria_properties,
#             "required": list(criteria_list) + ["summary_comment"]
#         }
#     }

#     # Call OpenAI chat with function schema
#     response = client.chat.completions.create(
#         model=AZURE_OPENAI_DEPLOYMENT_NAME,
#         messages=messages,
#         functions=[function_schema],
#         function_call={"name": "evaluate_resume"},
#         temperature=0,
#     )

#     # Parse function response JSON
#     args_json = response.choices[0].message.function_call.arguments
#     result = json.loads(args_json)

#     return result



# def calculate_weighted_score_manual(evaluation_result, criteria_with_weights):
#     criteria = [item["criterion"] for item in criteria_with_weights]
#     n = len(criteria)
#     descending_weights = list(range(n, 0, -1))
#     total_weight = sum(descending_weights)

#     total_weighted_score = 0
#     weight_map = {}

#     # print("Evaluation Result:", evaluation_result)  # Log to check structure

#     for i, criterion in enumerate(criteria):
#         # Check for the criterion in both formats (with and without the dot)
#         criterion_normalized = criterion.strip(".").lower()  # Normalize to lowercase, remove the dot
#         found = False

#         # Try to match the normalized criterion (both versions)
#         for key in evaluation_result:
#             if criterion_normalized == key.strip(".").lower():
#                 found = True
#                 score = evaluation_result[key]["score"]
#                 weight = descending_weights[i]
#                 total_weighted_score += score * weight
#                 weight_map[criterion] = weight
#                 break

#         if not found:
#             print(f"[ERROR] Missing criterion '{criterion}' in evaluation result.")

#     final_score = round((total_weighted_score / total_weight) / 10, 2)
#     return final_score, weight_map




import json
from openai import AzureOpenAI
from dotenv import load_dotenv
import os
import html

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
            
            ⚠️ Important Instructions for JSON formatting:
            - Use the EXACT criterion names provided in the criteria list as JSON keys (do not change casing, punctuation, or spacing). 
            - Return ALL criteria, even if the resume has zero evidence. 
            - For each criterion: assign a score between [0–100] and provide a brief explanation.
            - Add a 'summary_comment' as an overall evaluation.
            - Use the criteria_list exactly as provided. Do not change capitalization or formatting of keys.
            - Treat all comparisons as case-insensitive.
            - For example, if the criterion is ".net", also match ".Net", ".NET", "ASP.NET", "VB.NET", "C#.NET", or "Dot Net".
            - Always return the score and explanation under the original key from criteria_list, even if the match came from a synonym.



            Assign each criterion a score from [0,1,2 ..., 100]. Use this guide:
            - 90–100: Excellent alignment with clear, strong evidence.
            - 70–89: Good alignment with examples or relevant experience.
            - 50–69: Some alignment, may lack depth or relevance.
            - 0–49: Weak or no alignment.

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
        } for criterion in criteria_list  # Pass original criteria, including .net
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



def calculate_weighted_score_manual(evaluation_result, criteria_with_weights):
    criteria = [item["criterion"] for item in criteria_with_weights]
    n = len(criteria)
    descending_weights = list(range(n, 0, -1))
    total_weight = sum(descending_weights)

    total_weighted_score = 0
    weight_map = {}

    # print("Evaluation Result:", evaluation_result)  # Log to check structure

    for i, criterion in enumerate(criteria):
        # Check for the criterion in both formats (with and without the dot)
        criterion_normalized = criterion.strip(".").lower()  # Normalize to lowercase, remove the dot
        found = False

        # Try to match the normalized criterion (both versions)
        for key in evaluation_result:
            if criterion_normalized == key.strip(".").lower():
                found = True
                score = evaluation_result[key]["score"]
                weight = descending_weights[i]
                total_weighted_score += score * weight
                weight_map[criterion] = weight
                break

        if not found:
            print(f"[ERROR] Missing criterion '{criterion}' in evaluation result.")

    final_score = round((total_weighted_score / total_weight) / 10, 2)
    return final_score, weight_map


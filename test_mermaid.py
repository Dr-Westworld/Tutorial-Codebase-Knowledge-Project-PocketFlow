import os

# Store initial value
initial_api_key = os.getenv("GEMINI_PROJECT_ID", "").strip()



# Usage
print(f"API Key :{initial_api_key}")
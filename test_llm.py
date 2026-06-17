import os

from openai import OpenAI

client = OpenAI(api_key=os.getenv("API_KEY"), base_url=os.getenv("API_BASE_URL"))

try:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "test"}],
        # max_tokens=5,
    )

    msg = resp.choices[0].message
    print("API call succeeded.")
    print("Raw message object:", msg)
    print("Message content:", msg.content)

except Exception as e:
    print("API call FAILED.")
    print(e)

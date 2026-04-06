from openai import OpenAI

class GPTAnalyzer:
    def __init__(self, api_key: str, model="gpt-4o", temperature=0.7, max_tokens=800):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def analyze(self, full_input: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a Formula 1 editor. Write concise Telegram-ready posts in Russian with clear structure and no emojis in posts."
                    },
                    {
                        "role": "user",
                        "content": full_input
                    }
                ]
            )

            content = response.choices[0].message.content
            return content.strip() if content else ""

        except Exception as e:
            print(f"[GPTAnalyzer] Error: {e}")
            return ""

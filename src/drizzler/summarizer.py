"""
Text summarization module supporting Local LLMs (Ollama/OpenAI) and Google Gemini API.
"""

import logging
import os
import requests

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

logger = logging.getLogger(__name__)

# LLM server URL - configurable via environment variable
LLM_HOST = os.getenv("LLM_HOST", "http://localhost:8003")
# Default model - can be overridden via environment variable or parameter
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-coder:30b")
# Gemini API Key
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Supported summary languages
LANG_ENGLISH = "en"
LANG_KOREAN = "ko"
LANG_JAPANESE = "ja"

# Language display names
LANGUAGE_NAMES = {
    LANG_ENGLISH: "English",
    LANG_KOREAN: "Korean",
    LANG_JAPANESE: "Japanese"
}

# Unified professional summary prompt - comprehensive version
SUMMARY_PROMPT_TEMPLATE = """You are an expert editor at a prestigious knowledge publication (like Harvard Business Review or MIT Technology Review).
Your task is to RECONSTRUCT a video transcript into a definitive, long-form article.

## CRITICAL CONTEXT
- Video duration: {video_minutes} minutes
- Target reading time: ~{target_read_minutes} minutes
- Output language: {output_language}
- **CRITICAL RULE**: Do NOT summarize. Your goal is to "Expand and Elaborate." Every minute of the video should translate into approximately 150-200 words of text for long videos.

## YOUR MISSION
Transform the raw transcript into an authoritative reference material.
For a {video_minutes}-minute video, a 5-minute read is a FAILURE. You must provide a deep-dive experience that justifies the {target_read_minutes}-minute reading time.

## EXPANSION GUIDELINES (To prevent short outputs)
1. **Detail Restoration**: Include every single anecdote, case study, and supporting argument. If the speaker mentions a story, tell the whole story.
2. **Structural Depth**: Each major section (##) must contain at least 4-5 dense paragraphs.
3. **No Omission**: Do not skip "minor" points. In a prestigious journal, the nuance is in the details.
4. **Technical Padding**: When a technical term is mentioned, don't just define it—explain its context, importance, and how it relates to other concepts in the lecture.

## CONTENT REQUIREMENTS
- ALL major concepts and their granular sub-points
- ALL examples, analogies, and step-by-step methodologies
- ALL key statistics and data points
- Comparisons, pros/cons, and trade-offs
- Common misconceptions and the speaker's rebuttals

## WRITING STANDARDS
- Write ENTIRELY in {output_language}
- **Tone**: Formal, analytical, and sophisticated (HBR style)
- **Structure**:
  # [Compelling & Scholarly Headline]
  *~{target_read_minutes}분 읽기*

  [Hook paragraph: 150+ words setting the stage and explaining the "Why now?"]

  ## [Section 1: Major Topic]
  [Extensive explanation - Minimum 500 words for this section...]

  ## [Section 2: Major Topic]
  [Extensive explanation - Minimum 500 words for this section...]

  (Add as many sections as needed to cover the duration proportionally)

## Key Takeaways (Deep Analysis)
- **[Concept 1]**: Don't just list it. Provide a 3-4 sentence sophisticated analysis of this takeaway.
[Include 5-10 takeaways]

## 핵심 용어 및 개념 상세 정리
| 용어 | 맥락 및 심층 정의 |
|------|----------------|
| Term 1 | Provide a thorough explanation of how this was used in the lecture |

---

## TRANSCRIPT TO TRANSFORM:
{text}
"""

class TextSummarizer:
    """Handles text summarization using various LLM providers"""

    def __init__(self, provider: str = "openai", model: str = None, summary_lang: str = LANG_ENGLISH):
        self.model = model or LLM_MODEL
        self.llm_host = LLM_HOST
        self.summary_lang = summary_lang

        # Determine provider: if model name starts with gemini, use gemini
        if self.model.lower().startswith("gemini-"):
            self.provider = "gemini"
        else:
            self.provider = provider or "openai"

    def _get_prompt(self, text: str, video_minutes: int = 10) -> tuple[str, str]:
        """Get system and user prompts for summarization"""
        output_lang = LANGUAGE_NAMES.get(self.summary_lang, "English")

        # Calculate target reading time (approx 20-30% of video length)
        target_read = max(5, video_minutes // 4) if video_minutes > 15 else 5

        # Context window management
        # Gemini has 1M+, but for efficiency we limit based on video length
        max_chars = min(200000, max(20000, video_minutes * 600))

        system_prompt = f"You are a professional editor creating comprehensive articles. Write in-depth in {output_lang}."
        user_prompt = SUMMARY_PROMPT_TEMPLATE.format(
            video_minutes=video_minutes,
            target_read_minutes=target_read,
            output_language=output_lang,
            text=text[:max_chars]
        )

        return system_prompt, user_prompt

    def _call_gemini_api(self, system_prompt: str, user_prompt: str) -> str:
        """Call Google Gemini API"""
        if not HAS_GEMINI:
            raise ImportError("Package 'google-generativeai' is not installed.")
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY environment variable is not set.")

        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system_prompt
        )

        response = model.generate_content(user_prompt)
        return response.text if response.text else ""

    def _call_openai_api(self, system_prompt: str, user_prompt: str, timeout: int = 300) -> str:
        """Call OpenAI-compatible API"""
        try:
            response = requests.post(
                f"{self.llm_host}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 8192
                },
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    def _call_ollama_api(self, system_prompt: str, user_prompt: str, timeout: int = 300) -> str:
        """Call Ollama API"""
        try:
            response = requests.post(
                f"{self.llm_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 8192}
                },
                timeout=timeout
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            raise

    def summarize(self, text: str, video_minutes: int = 10) -> str:
        """Generate a summary using the configured provider"""
        if not text:
            return ""

        system_prompt, user_prompt = self._get_prompt(text, video_minutes)
        timeout = min(1200, max(180, video_minutes * 10)) # Gemini is faster, but local needs time

        try:
            if self.provider == "gemini":
                logger.info(f"Using Gemini: {self.model}")
                return self._call_gemini_api(system_prompt, user_prompt).strip()
            elif self.provider == "ollama":
                logger.info(f"Using Ollama: {self.model}")
                return self._call_ollama_api(system_prompt, user_prompt, timeout).strip()
            else:
                logger.info(f"Using OpenAI-compatible: {self.model}")
                return self._call_openai_api(system_prompt, user_prompt, timeout).strip()
        except Exception as e:
            return f"[Summarization failed: {str(e)}]"

"""
Text summarization module using open-source LLMs
Supports both Ollama API and OpenAI-compatible APIs (llama.cpp, vLLM, etc.)
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

# LLM server URL - configurable via environment variable
LLM_HOST = os.getenv("LLM_HOST", "http://localhost:8003")
# Default model - can be overridden via environment variable or parameter
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-coder:30b")

# Summarization modes
MODE_DEFAULT = "default"
MODE_LECTURE = "lecture"

# Lecture mode prompt template
LECTURE_PROMPT_TEMPLATE = """You are a professional technical editor who summarizes long-form spoken content
(such as YouTube lectures or talks) into a readable blog-style article.

TASK
Given INPUT_TEXT and VIDEO_LENGTH_MINUTES, produce a structured English summary
that matches the appropriate depth and density for the video length.

GENERAL RULES
- Write in clear, neutral English. No fluff, no marketing tone.
- Use Markdown.
- Do NOT invent facts. Preserve uncertainty if present.
- Optimize for skimmability: headings, bullets, short paragraphs.
- Focus on ideas, not speech patterns or repetition.
- Prefer topic-based summarization over chronological narration,
  especially for long lectures.

LENGTH-AWARE BEHAVIOR
- If VIDEO_LENGTH_MINUTES <= 4:
  - Extremely concise summary
  - Focus on the single main idea and takeaway

- If 4 < VIDEO_LENGTH_MINUTES <= 20:
  - Blog-style summary
  - 3–5 sections max
  - Light explanations, minimal examples

- If 20 < VIDEO_LENGTH_MINUTES <= 60:
  - Structured outline
  - Clear section hierarchy
  - Include reasoning, trade-offs, and key examples

- If VIDEO_LENGTH_MINUTES > 60:
  - Treat this as a lecture or workshop
  - Summarize by major topics or chapters, not timeline
  - Limit to 5–8 high-level sections
  - Each section should answer:
    - What is the core idea?
    - Why does it matter?
    - When or how is it used?
  - Aggressively remove repetition, anecdotes, and filler
  - Output should feel like "condensed lecture notes"

OUTPUT FORMAT (must follow exactly)

# One-Line Summary
(1–2 sentences)

# Key Takeaways
- 5–9 bullets (depending on length)

# Structured Summary
## 1. (Topic title)
- Core idea:
  - ...
- Explanation:
  - ...
- Practical implication (if any):
  - ...

## 2. (Topic title)
(same structure)

# Key Terms / Concepts
- **Term**: short explanation

# Actionable Notes / Follow-ups
- ...

# Quotable Lines (optional)
> Short, exact quotes (max 3, each under 25 words)

INPUT
VIDEO_LENGTH_MINUTES: {minutes}
INPUT_TEXT:
{text}
"""


class TextSummarizer:
    """Handles text summarization using various LLM providers"""

    def __init__(self, provider: str = "openai", model: str = None, mode: str = MODE_DEFAULT):
        self.provider = provider
        self.model = model or LLM_MODEL
        self.llm_host = LLM_HOST
        self.mode = mode

    def _get_prompt(self, text: str, lang: str = "en", video_minutes: int = 10) -> tuple[str, str]:
        """Get system and user prompts based on mode and language"""

        if self.mode == MODE_LECTURE:
            # Lecture mode - uses the detailed prompt template
            system_prompt = "You are a professional technical editor who creates structured summaries of lectures and talks."
            user_prompt = LECTURE_PROMPT_TEMPLATE.format(
                minutes=video_minutes,
                text=text[:8000]  # Allow more text for lecture mode
            )
            return system_prompt, user_prompt

        # Default mode - detect language and create appropriate prompt
        is_cjk = any(
            "\u4e00" <= char <= "\u9fff"  # Chinese
            or "\uac00" <= char <= "\ud7af"  # Korean
            or "\u3040" <= char <= "\u309f"  # Hiragana
            or "\u30a0" <= char <= "\u30ff"  # Katakana
            for char in text[:100]
        )

        if is_cjk:
            system_prompt = "당신은 동영상 내용을 요약하는 전문가입니다. 마크다운 형식으로 요약해 주세요."
            user_prompt = f"""다음 내용을 요약해 주세요:

# 동영상 내용 요약

## 주요 내용
주요 내용을 3~5개의 핵심 포인트로 정리해 주세요.

## 상세 요약
내용을 더 자세히 요약해 주세요.

---
원문 내용:
{text[:4000]}

요약은 원문과 동일한 언어로 작성해 주세요."""
        else:
            system_prompt = "You are an expert at summarizing video content. Please provide summaries in markdown format."
            user_prompt = f"""Please summarize the following content:

# Video Content Summary

## Key Points
List 3-5 main points from the content

## Detailed Summary
Provide a more detailed summary of the content

---
Original content:
{text[:4000]}

Please summarize in the same language as the original text."""

        return system_prompt, user_prompt

    def summarize_with_openai_compatible(self, text: str, lang: str = "en", video_minutes: int = 10) -> str | None:
        """Summarize text using OpenAI-compatible API (llama.cpp, vLLM, etc.)"""
        try:
            system_prompt, user_prompt = self._get_prompt(text, lang, video_minutes)

            # Call OpenAI-compatible API
            response = requests.post(
                f"{self.llm_host}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 4000 if self.mode == MODE_LECTURE else 2000,
                },
                timeout=180 if self.mode == MODE_LECTURE else 120,
            )

            if response.status_code == 200:
                result = response.json()
                summary = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                return summary
            else:
                logger.error(f"LLM API error: {response.status_code} - {response.text[:200]}")
                return None

        except requests.exceptions.ConnectionError:
            logger.error(
                f"Cannot connect to LLM server at {self.llm_host}. "
                "Please ensure the server is running or set LLM_HOST environment variable."
            )
            return None
        except Exception as e:
            logger.error(f"Error during LLM summarization: {e}")
            return None

    def summarize_with_ollama(self, text: str, lang: str = "en", video_minutes: int = 10) -> str | None:
        """Summarize text using Ollama API"""
        try:
            system_prompt, user_prompt = self._get_prompt(text, lang, video_minutes)

            # Combine system and user prompt for Ollama
            prompt = f"{system_prompt}\n\n{user_prompt}"

            # Call Ollama API
            response = requests.post(
                f"{self.llm_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                    },
                },
                timeout=180 if self.mode == MODE_LECTURE else 120,
            )

            if response.status_code == 200:
                result = response.json()
                summary = result.get("response", "")
                return summary
            else:
                logger.error(f"Ollama API error: {response.status_code}")
                return None

        except requests.exceptions.ConnectionError:
            logger.error(
                f"Cannot connect to Ollama at {self.llm_host}. "
                "Please ensure Ollama is running or set LLM_HOST environment variable."
            )
            return None
        except Exception as e:
            logger.error(f"Error during Ollama summarization: {e}")
            return None

    def summarize_with_transformers(self, text: str, lang: str = "en", video_minutes: int = 10) -> str | None:
        """Summarize text using Hugging Face Transformers"""
        try:
            from transformers import pipeline

            # Use a multilingual summarization model
            summarizer = pipeline(
                "summarization",
                model="facebook/bart-large-cnn",
                device=-1,
            )

            # Split text into chunks if too long
            max_chunk_size = 1024
            chunks = [
                text[i : i + max_chunk_size]
                for i in range(0, len(text), max_chunk_size)
            ]

            summaries = []
            for chunk in chunks[:3]:
                result = summarizer(
                    chunk, max_length=150, min_length=30, do_sample=False
                )
                summaries.append(result[0]["summary_text"])

            summary_md = f"""# Video Content Summary

## Key Points
{" ".join(summaries)}

---
*Generated using {self.model}*
"""
            return summary_md

        except ImportError:
            logger.error(
                "Transformers library not installed. Run: pip install transformers torch"
            )
            return None
        except Exception as e:
            logger.error(f"Error during Transformers summarization: {e}")
            return None

    def summarize(self, text: str, lang: str = "en", video_minutes: int = 10) -> str | None:
        """Main summarization method that routes to appropriate provider"""
        if not text or len(text.strip()) < 50:
            logger.warning("Text too short for meaningful summarization")
            return None

        logger.info(f"Summarizing with mode={self.mode}, provider={self.provider}, model={self.model}")

        if self.provider == "openai":
            return self.summarize_with_openai_compatible(text, lang, video_minutes)
        elif self.provider == "ollama":
            return self.summarize_with_ollama(text, lang, video_minutes)
        elif self.provider == "transformers":
            return self.summarize_with_transformers(text, lang, video_minutes)
        else:
            logger.error(f"Unknown provider: {self.provider}")
            return None

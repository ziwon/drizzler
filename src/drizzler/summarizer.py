"""
Text summarization module using open-source LLMs
"""

import logging

logger = logging.getLogger(__name__)


class TextSummarizer:
    """Handles text summarization using various LLM providers"""

    def __init__(self, provider: str = "ollama", model: str = "qwen2.5:3b"):
        self.provider = provider
        self.model = model

    def summarize_with_ollama(self, text: str, lang: str = "en") -> str | None:
        """Summarize text using Ollama API"""
        try:
            import requests

            # Detect if text is in Chinese/Korean/Japanese
            is_cjk = any(
                "\u4e00" <= char <= "\u9fff"  # Chinese
                or "\uac00" <= char <= "\ud7af"  # Korean
                or "\u3040" <= char <= "\u309f"  # Hiragana
                or "\u30a0" <= char <= "\u30ff"  # Katakana
                for char in text[:100]
            )

            # Create appropriate prompt based on language
            if is_cjk:
                prompt = f"""다음 내용을 요약해 주세요. 마크다운 형식으로 출력해 주세요:

# 동영상 내용 요약

## 주요 내용
주요 내용을 3~5개의 핵심 포인트로 정리해 주세요.

## 상세 요약
내용을 더 자세히 요약해 주세요.

---
원문 내용:
{text[:3000]}  # 토큰 제한을 피하기 위해 텍스트 길이를 제한합니다.

요약은 원문과 동일한 언어로 작성해 주세요"""
            else:
                prompt = f"""Please summarize the following content in markdown format:

# Video Content Summary

## Key Points
List 3-5 main points from the content

## Detailed Summary
Provide a more detailed summary of the content

---
Original content:
{text[:3000]}  # Limit text to avoid token limits

Please summarize in the same language as the original text."""

            # Call Ollama API
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                    },
                },
                timeout=60,
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
                "Cannot connect to Ollama. Please ensure Ollama is running (ollama serve)"
            )
            return None
        except Exception as e:
            logger.error(f"Error during Ollama summarization: {e}")
            return None

    def summarize_with_transformers(self, text: str, lang: str = "en") -> str | None:
        """Summarize text using Hugging Face Transformers"""
        try:
            from transformers import pipeline

            # Use a multilingual summarization model
            summarizer = pipeline(
                "summarization",
                model="facebook/bart-large-cnn",  # Can be replaced with multilingual models
                device=-1,  # Use CPU, set to 0 for GPU
            )

            # Split text into chunks if too long
            max_chunk_size = 1024
            chunks = [
                text[i : i + max_chunk_size]
                for i in range(0, len(text), max_chunk_size)
            ]

            summaries = []
            for chunk in chunks[:3]:  # Limit to first 3 chunks
                result = summarizer(
                    chunk, max_length=150, min_length=30, do_sample=False
                )
                summaries.append(result[0]["summary_text"])

            # Format as markdown
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

    def summarize(self, text: str, lang: str = "en") -> str | None:
        """Main summarization method that routes to appropriate provider"""
        if not text or len(text.strip()) < 50:
            logger.warning("Text too short for meaningful summarization")
            return None

        if self.provider == "ollama":
            return self.summarize_with_ollama(text, lang)
        elif self.provider == "transformers":
            return self.summarize_with_transformers(text, lang)
        else:
            logger.error(f"Unknown provider: {self.provider}")
            return None

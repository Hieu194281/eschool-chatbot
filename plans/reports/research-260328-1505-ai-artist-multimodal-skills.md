# Research Report: AI-Artist & AI-Multimodal Skills Analysis

**Date**: 2026-03-28
**Purpose**: Understanding image generation skills for implementing worksheet generation backend

---

## Executive Summary

Two skills handle image generation in claudekit-engineer:

1. **ai-artist**: Prompt engineering + curated template system using 129 prompts with BM25 search
2. **ai-multimodal**: Direct API integration with Google Gemini (Nano Banana), Imagen 4, and MiniMax

For your English vocabulary worksheet generator, **ai-multimodal** patterns are most relevant - direct API calls to Gemini/MiniMax for image generation.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        ai-artist                                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ User Concept │───▶│ BM25 Search  │───▶│ Prompt Match │      │
│  └──────────────┘    │ (core.py)    │    │ (129 curated)│      │
│                      └──────────────┘    └──────┬───────┘      │
│                                                  │              │
│  3 Modes: search | creative | wild               ▼              │
│                      ┌──────────────────────────────────────┐   │
│                      │ adapt_prompt() - Variable replacement│   │
│                      │ + Negative constraints                │   │
│                      └──────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                        ai-multimodal                              │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Gemini/Imagen   │  │    MiniMax      │  │  Media Tools    │  │
│  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤  │
│  │ • Nano Banana 2 │  │ • image-01      │  │ • Transcribe    │  │
│  │ • Nano Banana   │  │ • Hailuo Video  │  │ • Analyze       │  │
│  │   Flash/Pro     │  │ • TTS Speech    │  │ • Extract       │  │
│  │ • Imagen 4      │  │ • Music 2.5     │  │ • Convert docs  │  │
│  │ • Veo Video     │  │                 │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Key Implementation Patterns

### 1. API Key Resolution (Reusable Pattern)

```python
# Priority: env → skill .env → project .env → user global .env
def find_api_key() -> Optional[str]:
    # 1. Runtime environment
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key:
        return api_key

    # 2. Skill-specific .env files
    from dotenv import load_dotenv
    env_files = [
        skill_dir / '.env',        # Skill-specific
        skills_dir / '.env',       # Shared skills
        claude_dir / '.env',       # Project global
    ]
    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file, override=True)

    return os.getenv('GEMINI_API_KEY')
```

### 2. Gemini Image Generation (Core Pattern for Your Service)

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

# Nano Banana 2 - Recommended for worksheets (fast, good quality)
response = client.models.generate_content(
    model='gemini-3.1-flash-image-preview',
    contents='A vocabulary flashcard showing the word "APPLE" with a red apple illustration',
    config=types.GenerateContentConfig(
        response_modalities=['IMAGE'],  # MUST be uppercase
        image_config=types.ImageConfig(
            aspect_ratio='1:1',          # Square for flashcards
            image_size='2K'              # Uppercase K required
        )
    )
)

# Save image
for part in response.candidates[0].content.parts:
    if part.inline_data:
        with open('output.png', 'wb') as f:
            f.write(part.inline_data.data)
```

### 3. MiniMax Alternative (Cheaper for Batch)

```python
import requests

BASE_URL = "https://api.minimax.io/v1"

def generate_image(prompt: str, api_key: str) -> str:
    payload = {
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "n": 1,                    # Up to 9 images per batch
        "response_format": "url",
        "prompt_optimizer": True   # MiniMax auto-improves prompts
    }

    response = requests.post(
        f"{BASE_URL}/image_generation",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload
    )

    image_urls = response.json()["data"]["image_urls"]
    return image_urls[0]
```

### 4. BM25 Prompt Search (ai-artist Pattern)

```python
class BM25:
    """Rank prompts by relevance to user query"""

    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b

    def tokenize(self, text):
        text = re.sub(r'[^\w\s]', ' ', str(text).lower())
        return [w for w in text.split() if len(w) > 2]

    def fit(self, documents):
        # Build index: doc frequencies, IDF scores
        self.corpus = [self.tokenize(doc) for doc in documents]
        # ... compute IDF

    def score(self, query):
        # Return [(doc_idx, score), ...] sorted by relevance
        # ... BM25 scoring formula
```

---

## Models Comparison

| Model | Provider | Cost | Speed | Best For |
|-------|----------|------|-------|----------|
| `gemini-3.1-flash-image-preview` | Google | ~$0.07/img | Fast | **Recommended default** |
| `gemini-3-pro-image-preview` | Google | ~$0.13/img | Medium | Text-heavy images, 4K |
| `imagen-4.0-generate-001` | Google | ~$0.02/img | Medium | Production quality |
| `imagen-4.0-fast-generate-001` | Google | ~$0.01/img | Fastest | Bulk generation |
| `image-01` | MiniMax | ~$0.03/img | Fast | Batch (up to 9) |

**For vocabulary worksheets**: Use `gemini-3.1-flash-image-preview` for single images or MiniMax `image-01` for batch generation.

---

## Backend Service Architecture (Recommendation)

```
┌──────────────────────────────────────────────────────────────┐
│                  Worksheet Generator Service                   │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌────────────────┐   ┌────────────────┐   ┌────────────────┐ │
│  │  API Endpoint  │──▶│ Prompt Builder │──▶│ Image Generator│ │
│  │  /generate     │   │                │   │                │ │
│  └────────────────┘   └────────────────┘   └────────────────┘ │
│                                                    │          │
│                                                    ▼          │
│                       ┌────────────────────────────────────┐  │
│                       │         Provider Abstraction        │  │
│                       ├─────────────┬──────────────────────┤  │
│                       │   Gemini    │      MiniMax         │  │
│                       │  (default)  │   (batch/fallback)   │  │
│                       └─────────────┴──────────────────────┘  │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │                    Storage Layer                        │   │
│  │  • Cache generated images (S3/R2/local)                 │   │
│  │  • Prompt templates (JSON/CSV)                          │   │
│  │  • API key rotation for rate limits                     │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## Prompt Engineering for Vocabulary Worksheets

### Template Structure

```python
VOCAB_PROMPT_TEMPLATE = """
Educational vocabulary flashcard illustration:
- Word: "{word}" displayed prominently at top
- Clear, child-friendly illustration of {word}
- Clean white background
- Bold, readable sans-serif font
- Simple, colorful cartoon style
- No complex backgrounds or distractions
- Suitable for children ages 5-10

Style: Educational illustration, flat design, bright colors.
NEVER add watermarks. DO NOT include extra text or labels.
"""

def build_prompt(word: str, category: str = "general") -> str:
    return VOCAB_PROMPT_TEMPLATE.format(word=word.upper())
```

### Category-Specific Variations

```python
CATEGORY_STYLES = {
    "animals": "cute cartoon animal illustration, friendly expression",
    "food": "appetizing food illustration, simple plate presentation",
    "actions": "simple stick figure or cartoon demonstrating the action",
    "colors": "color swatch with labeled color name",
    "shapes": "clean geometric shape with labeled name",
}
```

---

## Error Handling Patterns

```python
def generate_with_fallback(prompt: str) -> dict:
    """Try Gemini first, fallback to MiniMax"""
    try:
        # Primary: Gemini Nano Banana 2
        result = generate_gemini(prompt)
        return {"status": "success", "provider": "gemini", **result}

    except Exception as e:
        if is_rate_limit_error(e):
            # Fallback: MiniMax
            try:
                result = generate_minimax(prompt)
                return {"status": "success", "provider": "minimax", **result}
            except:
                pass

        return {"status": "error", "error": str(e)}

def is_rate_limit_error(e: Exception) -> bool:
    """Check if error is rate limit or quota exceeded"""
    error_str = str(e).lower()
    return any(x in error_str for x in [
        'rate', 'quota', '429', 'resource_exhausted'
    ])
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `.claude/skills/ai-multimodal/scripts/gemini_batch_process.py` | Gemini API wrapper |
| `.claude/skills/ai-multimodal/scripts/minimax_api_client.py` | MiniMax HTTP client |
| `.claude/skills/ai-multimodal/scripts/minimax_generate.py` | MiniMax generation functions |
| `.claude/skills/ai-artist/scripts/generate.py` | Prompt modes + generation |
| `.claude/skills/ai-artist/scripts/core.py` | BM25 search engine |
| `.claude/skills/ai-multimodal/references/image-generation.md` | Full Gemini image gen docs |

---

## Quick Start Code for Your Service

```python
#!/usr/bin/env python3
"""Minimal vocabulary worksheet image generator"""

import os
from google import genai
from google.genai import types

def generate_vocab_image(word: str, output_path: str) -> bool:
    """Generate vocabulary illustration for a word."""
    client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

    prompt = f"""
    Educational vocabulary flashcard:
    - Word "{word.upper()}" at top in bold
    - Simple cartoon illustration of {word}
    - White background, colorful illustration
    - Child-friendly style
    NEVER add watermarks.
    """

    response = client.models.generate_content(
        model='gemini-3.1-flash-image-preview',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=['IMAGE'],
            image_config=types.ImageConfig(
                aspect_ratio='1:1',
                image_size='1K'  # Sufficient for worksheets
            )
        )
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data:
            with open(output_path, 'wb') as f:
                f.write(part.inline_data.data)
            return True

    return False

# Usage
if __name__ == "__main__":
    words = ["apple", "book", "cat", "dog"]
    for word in words:
        generate_vocab_image(word, f"{word}.png")
        print(f"Generated: {word}.png")
```

---

## Dependencies

```bash
pip install google-genai python-dotenv pillow requests
```

**API Keys Required**:
- `GEMINI_API_KEY`: https://aistudio.google.com/apikey
- `MINIMAX_API_KEY` (optional): https://platform.minimax.io

---

## Unresolved Questions

1. **Batch optimization**: Should you generate multiple vocabulary images in parallel or sequential? (Parallel recommended with rate limiting)
2. **Text rendering accuracy**: Gemini sometimes misspells words in images. Consider Pro model (`gemini-3-pro-image-preview`) for critical text rendering.
3. **Caching strategy**: Hash prompts to cache results and avoid regenerating identical images.

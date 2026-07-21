# Deep Dive: Image Generation Flow & Prompt Engineering

**Date**: 2026-03-28
**Purpose**: Understanding complete image generation flow in ai-multimodal skill and best practices for prompt engineering

---

## Table of Contents

1. [Complete Generation Flow](#1-complete-generation-flow)
2. [How Claude Invokes Image Generation](#2-how-claude-invokes-image-generation)
3. [API Abstraction Layers](#3-api-abstraction-layers)
4. [Prompt Engineering System](#4-prompt-engineering-system)
5. [Best Prompts from User Input](#5-best-prompts-from-user-input)
6. [Implementation Guide for Your Service](#6-implementation-guide-for-your-service)

---

## 1. Complete Generation Flow

### Sequence Diagram

```
┌─────────┐     ┌──────────────┐     ┌─────────────────┐     ┌─────────────┐
│  User   │     │ Claude Code  │     │ ai-multimodal   │     │ Gemini API  │
└────┬────┘     └──────┬───────┘     └────────┬────────┘     └──────┬──────┘
     │                 │                      │                      │
     │ "Generate image"│                      │                      │
     │────────────────▶│                      │                      │
     │                 │                      │                      │
     │                 │ Invoke skill         │                      │
     │                 │─────────────────────▶│                      │
     │                 │                      │                      │
     │                 │                      │ find_api_key()       │
     │                 │                      │──────────────────────│
     │                 │                      │                      │
     │                 │                      │ genai.Client(key)    │
     │                 │                      │─────────────────────▶│
     │                 │                      │                      │
     │                 │                      │ generate_content()   │
     │                 │                      │─────────────────────▶│
     │                 │                      │                      │
     │                 │                      │ Image bytes          │
     │                 │                      │◀─────────────────────│
     │                 │                      │                      │
     │                 │ Save to docs/assets  │                      │
     │                 │◀─────────────────────│                      │
     │                 │                      │                      │
     │ Display result  │                      │                      │
     │◀────────────────│                      │                      │
```

### Detailed Flow Steps

#### Step 1: Entry Point Selection

```python
# gemini_batch_process.py determines which API to use based on model
if model.startswith('imagen-') or model in IMAGEN_MODELS:
    # Use Imagen 4 generate_images() API
    result = generate_image_imagen4(client, prompt, model, ...)
else:
    # Use Nano Banana generate_content() API
    result = process_file(client, file_path=None, prompt, model, task='generate', ...)
```

#### Step 2: API Key Resolution Chain

```python
def find_api_key() -> Optional[str]:
    """Priority chain for API key lookup"""

    # 1. Centralized resolver (recommended)
    if CENTRALIZED_RESOLVER_AVAILABLE:
        return resolve_env('GEMINI_API_KEY', skill='ai-multimodal')

    # 2. Runtime environment
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key:
        return api_key

    # 3. .env file chain
    env_files = [
        claude_dir / '.env',       # ~/.claude/.env
        skills_dir / '.env',       # ~/.claude/skills/.env
        skill_dir / '.env',        # ~/.claude/skills/ai-multimodal/.env
    ]
    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file, override=True)

    return os.getenv('GEMINI_API_KEY')
```

#### Step 3: Client Initialization with Key Rotation

```python
# For high-volume usage: multiple keys auto-rotate on rate limit
if KEY_ROTATION_AVAILABLE:
    all_keys = find_all_api_keys()  # GEMINI_API_KEY, GEMINI_API_KEY_2, etc.
    if len(all_keys) > 1:
        rotator = KeyRotator(keys=all_keys, verbose=verbose)
        api_key = rotator.get_key()

client = genai.Client(api_key=api_key)
```

#### Step 4: Generate Content API Call

```python
# Nano Banana (Gemini native image generation)
config_args = {
    'response_modalities': ['IMAGE'],  # MUST be uppercase
}

# Build image config
image_config_args = {}
if aspect_ratio:
    image_config_args['aspect_ratio'] = aspect_ratio
if image_size:
    image_config_args['image_size'] = image_size  # Must be uppercase K: 1K, 2K, 4K

if image_config_args:
    config_args['image_config'] = types.ImageConfig(**image_config_args)

config = types.GenerateContentConfig(**config_args)

# Make API call
response = client.models.generate_content(
    model=model,                    # e.g., 'gemini-3.1-flash-image-preview'
    contents=[prompt],              # User's prompt
    config=config
)
```

#### Step 5: Extract and Save Image

```python
if hasattr(response, 'candidates'):
    for i, part in enumerate(response.candidates[0].content.parts):
        if part.inline_data:
            # Determine output directory
            project_root = find_project_root()  # Looks for .git or .claude
            output_dir = project_root / 'docs' / 'assets'
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save image
            output_file = output_dir / f"generated_{i}.png"
            with open(output_file, 'wb') as f:
                f.write(part.inline_data.data)
```

---

## 2. How Claude Invokes Image Generation

### Skill Activation

When user types `/ck:ai-multimodal <file> <prompt>` or Claude detects image generation need:

```bash
# Direct CLI usage
python scripts/gemini_batch_process.py \
  --task generate \
  --prompt "A vocabulary flashcard for 'APPLE'" \
  --model gemini-3.1-flash-image-preview \
  --aspect-ratio 1:1 \
  -v

# Or via ai-artist for prompt engineering
python scripts/generate.py "vocabulary flashcard apple" \
  -o output.png \
  --mode search \
  -ar 1:1
```

### Error Handling Chain

```python
# Rate limit → Key rotation
if is_rate_limit_error(e) and rotator:
    rotator.mark_rate_limited(str(error))
    new_key = rotator.get_key()
    client = genai.Client(api_key=new_key)
    # Retry

# Billing required → Fallback to cheaper model
if result.get('status') == 'billing_required':
    result = process_file(..., model=IMAGE_MODEL_FALLBACK)

# Free tier → Clear error message
if _is_free_tier_quota_error(e):
    result['error'] = FREE_TIER_NO_ACCESS_MSG
```

---

## 3. API Abstraction Layers

### Layer 1: Imagen 4 vs Nano Banana

| Feature | Imagen 4 | Nano Banana (Gemini) |
|---------|----------|---------------------|
| API Method | `generate_images()` | `generate_content()` |
| Config Type | `GenerateImagesConfig` | `GenerateContentConfig` |
| Prompt Param | `prompt` (string) | `contents` (string/list) |
| Multi-image | ✅ `numberOfImages` (1-4) | ❌ Single per request |
| Multi-turn chat | ❌ | ✅ Conversational |
| Reference images | ❌ | ✅ Up to 14 |
| Response access | `generated_images[i].image.image_bytes` | `candidates[0].content.parts[i].inline_data.data` |

### Layer 2: MiniMax Alternative

```python
# minimax_api_client.py - HTTP REST wrapper
BASE_URL = "https://api.minimax.io/v1"

def api_post(endpoint: str, payload: Dict, api_key: str) -> Dict:
    response = requests.post(
        f"{BASE_URL}/{endpoint}",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload
    )
    return response.json()

# minimax_generate.py - Image generation
def generate_image(api_key, prompt, model='image-01', aspect_ratio='1:1', n=1):
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "n": min(n, 9),            # Up to 9 images per batch
        "response_format": "url",
        "prompt_optimizer": True   # MiniMax auto-enhances prompts
    }
    result = api_post("image_generation", payload, api_key)
    return result["data"]["image_urls"]
```

---

## 4. Prompt Engineering System

### Core Principle: Narrative > Keywords

```
❌ Bad:  "cat, 4k, masterpiece, trending, professional, ultra detailed"
✅ Good: "A fluffy orange tabby cat with green eyes lounging on a
         sun-drenched windowsill. Soft morning light creates a warm glow.
         Shot with 50mm lens at f/1.8. Natural lighting, documentary style."
```

### Universal Prompt Structure

```
[Subject + Details] [Action/Pose] [Setting/Environment]
[Style/Medium] [Artist/Movement Reference]
[Lighting] [Camera/Lens] [Composition]
[Quality Modifiers] [Aspect Ratio]
```

### Nano Banana-Specific Techniques

| Technique | Example | Purpose |
|-----------|---------|---------|
| **ALL CAPS** | `Text MUST be centered` | Force attention to critical requirements |
| **Hex colors** | `#9F2B68` | Exact color control |
| **Negative constraints** | `NEVER add watermarks. DO NOT include labels.` | Explicit exclusions |
| **Photography anchors** | `Captured with Canon EOS 90D, 85mm lens, f/1.8` | Trigger realism |
| **Structured edits** | `Make ALL edits: - [1] - [2] - [3]` | Multi-step changes |
| **Complex logic** | `Eyes MUST be heterochromatic matching fur colors` | Precise conditions |
| **Identity lock** | `Use reference as EXACT facial reference. STRICT identity lock.` | Face preservation |

### BM25 Prompt Matching (ai-artist)

```python
# core.py - BM25 search for 129 curated prompts
class BM25:
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1  # Term frequency saturation
        self.b = b    # Length normalization

    def tokenize(self, text):
        """Lowercase, remove punctuation, filter short words"""
        text = re.sub(r'[^\w\s]', ' ', str(text).lower())
        return [w for w in text.split() if len(w) > 2]

    def fit(self, documents):
        """Build IDF index"""
        self.corpus = [self.tokenize(doc) for doc in documents]
        self.N = len(self.corpus)
        self.avgdl = sum(len(doc) for doc in self.corpus) / self.N

        # Document frequency for IDF
        for doc in self.corpus:
            for word in set(doc):
                self.doc_freqs[word] += 1

        # Compute IDF scores
        for word, freq in self.doc_freqs.items():
            self.idf[word] = log((self.N - freq + 0.5) / (freq + 0.5) + 1)

    def score(self, query):
        """Score all documents against query"""
        query_tokens = self.tokenize(query)
        scores = []

        for idx, doc in enumerate(self.corpus):
            score = 0
            doc_len = len(doc)
            term_freqs = Counter(doc)

            for token in query_tokens:
                if token in self.idf:
                    tf = term_freqs[token]
                    idf = self.idf[token]
                    # BM25 formula
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                    score += idf * numerator / denominator

            scores.append((idx, score))

        return sorted(scores, key=lambda x: x[1], reverse=True)
```

---

## 5. Best Prompts from User Input

### Prompt Transformation Pipeline

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    USER INPUT TRANSFORMATION PIPELINE                     │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  User Input: "apple flashcard"                                           │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ STEP 1: CONTEXT EXTRACTION                                       │    │
│  │ • Subject: apple                                                 │    │
│  │ • Use case: flashcard (educational)                              │    │
│  │ • Implicit: child-friendly, clear, simple                        │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ STEP 2: TEMPLATE MATCHING (BM25)                                 │    │
│  │ • Search 129 curated prompts for "flashcard" + "educational"    │    │
│  │ • Top match: Quote card template (score: 4.2)                    │    │
│  │ • Fallback: Build from scratch                                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ STEP 3: PROMPT ASSEMBLY                                          │    │
│  │ Template + Subject + Style + Constraints                         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│       │                                                                  │
│       ▼                                                                  │
│  Final Prompt:                                                           │
│  "Educational vocabulary flashcard illustration:                         │
│   - Word 'APPLE' displayed prominently at top in bold sans-serif        │
│   - Clear, colorful cartoon illustration of a red apple                 │
│   - Clean white background, child-friendly style                        │
│   - Bright, cheerful colors, simple shapes                              │
│   Professional quality. NEVER add watermarks. DO NOT include labels."   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Template-Based Prompt Builder

```python
# For your vocabulary worksheet service
TEMPLATES = {
    "flashcard": """
Educational vocabulary flashcard illustration:
- Word "{word}" displayed prominently at top in bold sans-serif font
- Clear, child-friendly illustration of {word}
- Clean white background
- Simple, colorful cartoon style
- Suitable for children ages 5-10
NEVER add watermarks. DO NOT include extra text or labels.
""",

    "matching": """
Educational matching worksheet element:
- {word} illustration only, no text
- Simple line art style suitable for coloring
- Clear outline, recognizable shape
- White background
NEVER add text or labels.
""",

    "scene": """
Vocabulary scene illustration for "{word}":
- The word "{word}" shown in context/action
- Multiple elements showing usage
- Cartoon style, colorful, educational
- 16:9 aspect ratio for worksheet layout
NEVER add watermarks.
"""
}

def build_prompt(word: str, template_type: str = "flashcard") -> str:
    """Build optimized prompt from user input."""
    template = TEMPLATES.get(template_type, TEMPLATES["flashcard"])
    prompt = template.format(word=word.upper())
    return prompt
```

### Variable Replacement System (ai-artist pattern)

```python
def adapt_prompt(template_prompt: str, concept: str) -> str:
    """Adapt curated template to user's concept."""
    prompt = template_prompt

    # Replace common variable patterns
    replacements = {
        r'\{argument name="[^"]*" default="[^"]*"\}': concept,  # Raycast-style
        r'\[insert [^\]]+\]': concept,                          # Bracket variables
        r'\[subject\]': concept,
        r'\[concept\]': concept,
        r'\[product\]': concept,
    }

    for pattern, replacement in replacements.items():
        prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)

    # Ensure negative constraints exist (Nano Banana best practice)
    if "NEVER" not in prompt and "DO NOT" not in prompt:
        prompt += " NEVER add watermarks or unwanted text. DO NOT include labels."

    return prompt
```

### Style Keyword Mapping

```python
STYLE_KEYWORDS = {
    "photorealistic": "photorealistic, professional photography, 8K, RAW, natural lighting",
    "cinematic": "cinematic, film still, anamorphic lens, dramatic lighting, movie poster",
    "illustration": "digital illustration, artistic, stylized, clean lines",
    "minimalist": "minimalist, clean design, white space, simple shapes",
    "cartoon": "cartoon style, colorful, child-friendly, simple shapes, bright colors",
    "watercolor": "watercolor painting, soft edges, flowing colors, artistic",
}

MOOD_KEYWORDS = {
    "professional": "professional, clean, corporate, polished",
    "energetic": "dynamic, bold, vibrant, high energy",
    "calm": "serene, peaceful, soft, tranquil",
    "playful": "fun, cheerful, colorful, whimsical",
}

def enhance_prompt(base_prompt: str, style: str = "cartoon", mood: str = "playful") -> str:
    """Add style and mood keywords to base prompt."""
    style_kw = STYLE_KEYWORDS.get(style, "")
    mood_kw = MOOD_KEYWORDS.get(mood, "")
    return f"{base_prompt} {style_kw}. {mood_kw}."
```

---

## 6. Implementation Guide for Your Service

### Recommended Architecture (Separated by Use Case)

```
services/
├── flashcard_generator.py      # Flashcard-specific logic + prompts
├── worksheet_generator.py      # Worksheet-specific logic + prompts
└── shared/
    ├── gemini_client.py        # Shared API wrapper (DRY)
    └── prompt_utils.py         # Shared utilities
```

### Why Separate?

| Aspect | Flashcard | Worksheet |
|--------|-----------|-----------|
| Purpose | Single word + illustration | Multiple elements, layout |
| Aspect Ratio | 1:1 or 4:3 (card) | 16:9 or A4 (page) |
| Complexity | Simple, one focal point | Complex, sections |
| Prompts | Short, focused | Longer, structured |

---

### Shared Module: `shared/gemini_client.py`

```python
#!/usr/bin/env python3
"""Shared Gemini API client - reused by all generators."""

import os
from typing import Optional, Dict
from pathlib import Path

from google import genai
from google.genai import types


class GeminiClient:
    """Wrapper for Gemini API with common configuration."""

    DEFAULT_MODEL = 'gemini-3.1-flash-image-preview'  # Nano Banana 2

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found")
        self.client = genai.Client(api_key=self.api_key)

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        aspect_ratio: str = "1:1",
        image_size: str = "1K",
        model: Optional[str] = None
    ) -> Dict:
        """Generate image and save to file."""
        try:
            response = self.client.models.generate_content(
                model=model or self.DEFAULT_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=['IMAGE'],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size
                    )
                )
            )

            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, 'wb') as f:
                        f.write(part.inline_data.data)
                    return {"status": "success", "output": output_path, "prompt": prompt}

            return {"status": "error", "error": "No image in response"}

        except Exception as e:
            return {"status": "error", "error": str(e)}
```

### Shared Module: `shared/prompt_utils.py`

```python
#!/usr/bin/env python3
"""Shared prompt utilities."""

# Common suffix for all prompts (Nano Banana best practice)
NEGATIVE_CONSTRAINTS = "NEVER add watermarks or unwanted text. DO NOT include extra labels."


def append_constraints(prompt: str) -> str:
    """Append negative constraints if not present."""
    if "NEVER" not in prompt and "DO NOT" not in prompt:
        return f"{prompt.strip()}\n{NEGATIVE_CONSTRAINTS}"
    return prompt


def format_word(word: str) -> str:
    """Standardize word formatting."""
    return word.strip().upper()
```

---

### Flashcard Generator: `flashcard_generator.py`

```python
#!/usr/bin/env python3
"""
Flashcard Image Generator

Generates vocabulary flashcards: single word + illustration.
Optimized for card-like formats (1:1, 4:3).
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path

from shared.gemini_client import GeminiClient
from shared.prompt_utils import append_constraints, format_word


@dataclass
class FlashcardConfig:
    """Configuration for flashcard generation."""
    style: str = "cartoon"           # cartoon, realistic, watercolor, line_art
    mood: str = "playful"            # playful, calm, energetic
    aspect_ratio: str = "1:1"        # 1:1 (square), 4:3 (standard card)
    image_size: str = "1K"
    show_word: bool = True           # Display word text on card


class FlashcardGenerator:
    """Generate vocabulary flashcard images."""

    # Flashcard-specific templates
    TEMPLATES = {
        "with_word": """
Educational vocabulary flashcard:
- Word "{word}" displayed prominently at top in bold, readable sans-serif font
- Clear, child-friendly illustration of {word} below the text
- Clean white background
- {style_desc}
- {mood_desc}
- Suitable for children ages 5-10
- Single focal point, no distractions
""",
        "image_only": """
Vocabulary flashcard illustration:
- Clear, child-friendly illustration of {word}
- NO text, NO labels, NO words
- Clean white background
- {style_desc}
- {mood_desc}
- Simple, recognizable, single focal point
"""
    }

    STYLE_MAP = {
        "cartoon": "colorful cartoon style, simple shapes, bold outlines, bright colors",
        "realistic": "photorealistic style, detailed, natural colors",
        "watercolor": "watercolor painting style, soft edges, artistic",
        "line_art": "clean line art, black outlines, suitable for coloring",
    }

    MOOD_MAP = {
        "playful": "cheerful, fun, bright colors",
        "calm": "soft, pastel colors, peaceful",
        "energetic": "vibrant, dynamic, bold colors",
    }

    def __init__(self, api_key: Optional[str] = None):
        self.client = GeminiClient(api_key)

    def build_prompt(self, word: str, config: FlashcardConfig) -> str:
        """Build flashcard-specific prompt."""
        template_key = "with_word" if config.show_word else "image_only"
        template = self.TEMPLATES[template_key]

        prompt = template.format(
            word=format_word(word),
            style_desc=self.STYLE_MAP.get(config.style, config.style),
            mood_desc=self.MOOD_MAP.get(config.mood, config.mood)
        )

        return append_constraints(prompt)

    def generate(
        self,
        word: str,
        output_path: str,
        config: Optional[FlashcardConfig] = None
    ) -> Dict:
        """Generate a single flashcard image."""
        config = config or FlashcardConfig()
        prompt = self.build_prompt(word, config)

        result = self.client.generate_image(
            prompt=prompt,
            output_path=output_path,
            aspect_ratio=config.aspect_ratio,
            image_size=config.image_size
        )
        result["word"] = word
        result["type"] = "flashcard"
        return result

    def batch_generate(
        self,
        words: List[str],
        output_dir: str,
        config: Optional[FlashcardConfig] = None
    ) -> List[Dict]:
        """Generate flashcards for multiple words."""
        results = []
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        for word in words:
            output_path = f"{output_dir}/flashcard_{word.lower()}.png"
            result = self.generate(word, output_path, config)
            results.append(result)

        return results


# Usage
if __name__ == "__main__":
    generator = FlashcardGenerator()

    # Single flashcard
    result = generator.generate(
        word="apple",
        output_path="./output/flashcard_apple.png",
        config=FlashcardConfig(style="cartoon", mood="playful")
    )
    print(f"Generated: {result}")

    # Batch
    words = ["apple", "book", "cat"]
    results = generator.batch_generate(words, "./output/flashcards")
    print(f"Generated {len(results)} flashcards")
```

---

### Worksheet Generator: `worksheet_generator.py`

```python
#!/usr/bin/env python3
"""
Worksheet Image Generator

Generates educational worksheet images with multiple elements.
Optimized for page layouts (16:9, A4-like).
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path

from shared.gemini_client import GeminiClient
from shared.prompt_utils import append_constraints, format_word


@dataclass
class WorksheetConfig:
    """Configuration for worksheet generation."""
    worksheet_type: str = "matching"   # matching, scene, word_grid, fill_blank
    style: str = "line_art"            # line_art (for coloring), cartoon, flat
    aspect_ratio: str = "16:9"         # 16:9 (landscape), 3:4 (portrait A4-like)
    image_size: str = "2K"             # Larger for worksheets
    num_items: int = 4                 # Number of items in worksheet


class WorksheetGenerator:
    """Generate educational worksheet images."""

    # Worksheet-specific templates (more complex, layout-focused)
    TEMPLATES = {
        "matching": """
Educational matching worksheet layout:
- Grid of {num_items} distinct illustrations arranged in 2 rows
- Items to match: {words_list}
- Each illustration is clearly separated with space between
- {style_desc}
- Clean white background with light grid lines
- NO text labels on illustrations (text added separately)
- Each item in its own box/cell
- Simple, recognizable illustrations suitable for children
""",
        "scene": """
Educational vocabulary scene illustration:
- A scene containing these items: {words_list}
- Each item clearly visible and identifiable
- {style_desc}
- Natural context showing items in use
- Colorful, engaging for children ages 5-10
- 16:9 landscape format suitable for worksheet header
""",
        "word_grid": """
Vocabulary word grid worksheet:
- {num_items} separate illustration boxes arranged in a grid
- Each box contains ONE clear illustration
- Items: {words_list}
- {style_desc}
- White background, thin borders between boxes
- NO text inside boxes
- Equal-sized boxes, neat arrangement
""",
        "fill_blank": """
Fill-in-the-blank worksheet illustration:
- Scene showing: {words_list}
- {style_desc}
- Key items slightly highlighted or emphasized
- Space around items for writing
- Educational, clear context
- Clean layout suitable for worksheet
"""
    }

    STYLE_MAP = {
        "line_art": "clean black line art, suitable for coloring, simple outlines",
        "cartoon": "colorful cartoon style, child-friendly, bold outlines",
        "flat": "flat design, geometric shapes, modern educational style",
    }

    def __init__(self, api_key: Optional[str] = None):
        self.client = GeminiClient(api_key)

    def build_prompt(self, words: List[str], config: WorksheetConfig) -> str:
        """Build worksheet-specific prompt."""
        template = self.TEMPLATES.get(config.worksheet_type, self.TEMPLATES["matching"])

        words_formatted = [format_word(w) for w in words]
        words_list = ", ".join(words_formatted)

        prompt = template.format(
            words_list=words_list,
            num_items=config.num_items,
            style_desc=self.STYLE_MAP.get(config.style, config.style)
        )

        return append_constraints(prompt)

    def generate(
        self,
        words: List[str],
        output_path: str,
        config: Optional[WorksheetConfig] = None
    ) -> Dict:
        """Generate a single worksheet image."""
        config = config or WorksheetConfig()
        config.num_items = len(words)
        prompt = self.build_prompt(words, config)

        result = self.client.generate_image(
            prompt=prompt,
            output_path=output_path,
            aspect_ratio=config.aspect_ratio,
            image_size=config.image_size
        )
        result["words"] = words
        result["type"] = f"worksheet_{config.worksheet_type}"
        return result


# Usage
if __name__ == "__main__":
    generator = WorksheetGenerator()

    # Matching worksheet
    result = generator.generate(
        words=["apple", "banana", "orange", "grape"],
        output_path="./output/worksheet_fruits.png",
        config=WorksheetConfig(
            worksheet_type="matching",
            style="line_art",
            aspect_ratio="16:9"
        )
    )
    print(f"Generated: {result}")

    # Scene worksheet
    result = generator.generate(
        words=["cat", "dog", "bird"],
        output_path="./output/worksheet_animals_scene.png",
        config=WorksheetConfig(worksheet_type="scene", style="cartoon")
    )
    print(f"Generated: {result}")
```

---

### REST API: `api.py`

```python
#!/usr/bin/env python3
"""FastAPI endpoints for both generators."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import base64

from flashcard_generator import FlashcardGenerator, FlashcardConfig
from worksheet_generator import WorksheetGenerator, WorksheetConfig

app = FastAPI(title="Vocabulary Image Generator API")


# === Flashcard Endpoints ===

class FlashcardRequest(BaseModel):
    word: str
    style: str = "cartoon"
    mood: str = "playful"
    show_word: bool = True

@app.post("/flashcard/generate")
async def generate_flashcard(req: FlashcardRequest):
    generator = FlashcardGenerator()
    config = FlashcardConfig(style=req.style, mood=req.mood, show_word=req.show_word)

    output_path = f"/tmp/flashcard_{req.word}.png"
    result = generator.generate(req.word, output_path, config)

    if result["status"] == "success":
        with open(output_path, "rb") as f:
            return {"image": base64.b64encode(f.read()).decode(), "prompt": result["prompt"]}
    raise HTTPException(status_code=500, detail=result["error"])


class FlashcardBatchRequest(BaseModel):
    words: List[str]
    style: str = "cartoon"

@app.post("/flashcard/batch")
async def batch_flashcards(req: FlashcardBatchRequest):
    generator = FlashcardGenerator()
    config = FlashcardConfig(style=req.style)
    results = generator.batch_generate(req.words, "/tmp/flashcards", config)
    return {"results": results}


# === Worksheet Endpoints ===

class WorksheetRequest(BaseModel):
    words: List[str]
    worksheet_type: str = "matching"
    style: str = "line_art"

@app.post("/worksheet/generate")
async def generate_worksheet(req: WorksheetRequest):
    generator = WorksheetGenerator()
    config = WorksheetConfig(worksheet_type=req.worksheet_type, style=req.style)

    output_path = f"/tmp/worksheet_{req.worksheet_type}.png"
    result = generator.generate(req.words, output_path, config)

    if result["status"] == "success":
        with open(output_path, "rb") as f:
            return {"image": base64.b64encode(f.read()).decode(), "prompt": result["prompt"]}
    raise HTTPException(status_code=500, detail=result["error"])
```

---

## Key Takeaways

1. **API Selection**: Use `gemini-3.1-flash-image-preview` (Nano Banana 2) for fast, quality results
2. **Prompt Structure**: Narrative paragraphs > keyword lists
3. **Critical Formatting**: `response_modalities=['IMAGE']` (uppercase), `image_size='1K'` (uppercase K)
4. **Negative Constraints**: Always end with `NEVER add watermarks. DO NOT include labels.`
5. **Template System**: Pre-build templates for common use cases, use variable replacement
6. **Error Handling**: Implement key rotation for rate limits, fallback models for billing issues

---

## Unresolved Questions

1. **Text rendering accuracy**: Gemini sometimes misspells words. For critical text, consider:
   - Using `gemini-3-pro-image-preview` (better text rendering)
   - Generating text-free images and overlaying text programmatically

2. **Batch efficiency**: For 100+ images, consider:
   - MiniMax batch API (9 images per call)
   - Parallel requests with rate limiting
   - Caching with content hashing

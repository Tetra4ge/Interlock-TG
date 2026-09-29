import re
import unicodedata
from collections import Counter

def normalize_for_match(s: str) -> str:
    """Normalize text for reliable string matching, removing weird unicode and hyphenation."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[‘’]", "'", s)
    s = re.sub(r"[“”]", '"', s)
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"-\n(?=[a-z])", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()

def find_furniture(pages: list[str], ratio: float = 0.6) -> set[str]:
    """Find repeating headers/footers across pages."""
    counts = Counter()
    for text in pages:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        edge = lines[:2] + lines[-2:]
        counts.update({re.sub(r"\d+", "", l) for l in edge})
    n = len(pages)
    return {l for l, c in counts.items() if l and n > 0 and c / n >= ratio}

def clean_page_text(text: str, furniture: set[str]) -> str:
    """Clean the text of a single page by removing furniture, fixing hyphens and spaces."""
    lines = text.splitlines()
    cleaned_lines = []
    
    # Remove header/footer furniture
    for line in lines:
        stripped_digits = re.sub(r"\d+", "", line.strip())
        if stripped_digits in furniture and stripped_digits:
            continue
        cleaned_lines.append(line)
        
    text = "\n".join(cleaned_lines)
    
    # Hyphenation: join "govern-\nance"
    text = re.sub(r"-\n(?=[a-z])", "", text)
    
    # Whitespace: collapse runs of spaces
    text = re.sub(r"[ \t]+", " ", text)
    # Keep single newlines between lines and double newlines between paragraphs
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # Unicode normalization
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[‐-―]", "-", text)
    
    return text.strip()

def estimate_tokens(text: str) -> int:
    """
    Approximate token count for English text (roughly 4 chars per token).
    Adjust this divisor if using a specific tokenizer.
    """
    return max(1, len(text) // 4)

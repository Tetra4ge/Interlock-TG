import uuid


def generate_id() -> str:
    """
    Generate a unique ID.
    Using UUID4 hex representation.
    """
    return uuid.uuid4().hex

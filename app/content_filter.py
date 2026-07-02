"""Profanity filtering for user-submitted names."""

from better_profanity import profanity

profanity.load_censor_words()


def contains_profanity(text: str) -> bool:
    return profanity.contains_profanity(text)

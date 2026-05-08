"""
Markov chain text generation service.
Encapsulates model loading, sentence generation, message learning,
and periodic retraining.
"""

import asyncio
import logging
import os
import re

import markovify

logger = logging.getLogger(__name__)

# Global model instance (loaded once at startup, refreshed on retrain)
_markov_model = None
_model_loaded = False

# Default paths (can be overridden via env vars or args)
DEFAULT_MODEL_PATH = "./model.json"
DEFAULT_BASE_CORPUS_PATH = "./messages_clean.txt"
DEFAULT_LEARNED_PATH = "./messages_learned.txt"


def load_markov_model(model_path: str = DEFAULT_MODEL_PATH) -> bool:
    """Load the Markov model from JSON. Returns True on success."""
    global _markov_model, _model_loaded

    logger.info("Loading Markov model...")

    if not os.path.exists(model_path):
        logger.error(f"Markov model not found at: {model_path}")
        _model_loaded = False
        return False

    try:
        with open(model_path, "r", encoding="utf-8") as f:
            json_str = f.read()
        _markov_model = markovify.NewlineText.from_json(json_str)
        _model_loaded = True
        logger.info("Markov model loaded successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to load Markov model: {e}", exc_info=True)
        _markov_model = None
        _model_loaded = False
        return False


def is_model_available() -> bool:
    """Check whether the model was loaded successfully."""
    return _model_loaded and _markov_model is not None


def generate_markov_sentence(seed: str | None = None, max_retries: int = 5) -> str:
    """
    Generate a sentence using the loaded Markov model.

    Args:
        seed: Optional starting word/phrase. If provided, tries
              ``make_sentence_with_start(seed, strict=False)``.
        max_retries: Number of generation attempts before giving up.

    Returns:
        A generated sentence, or a fallback string if generation fails.
    """
    if not is_model_available():
        logger.warning("generate_markov_sentence called but model is not available")
        return "..."

    seed = seed.strip() if seed else None

    # If a seed is provided, try seed-based generation first
    if seed:
        for attempt in range(1, max_retries + 1):
            try:
                sentence = _markov_model.make_sentence_with_start(seed, strict=False)
                if sentence:
                    logger.debug(f"Markov seed generation succeeded on attempt {attempt}")
                    return sentence
            except (KeyError, markovify.text.ParamError):
                # Seed not found in model — will fall back below
                break
            except Exception as e:
                logger.warning(f"Markov seed generation error (attempt {attempt}): {e}")

    # Fallback: random generation
    for attempt in range(1, max_retries + 1):
        try:
            sentence = _markov_model.make_sentence()
            if sentence:
                logger.debug(f"Markov random generation succeeded on attempt {attempt}")
                return sentence
        except Exception as e:
            logger.warning(f"Markov random generation error (attempt {attempt}): {e}")

    logger.warning("Markov generation failed after all retries")
    return "xd"


def _clean_message(text: str) -> str | None:
    """
    Clean a raw message for learning.
    Returns None if the message should be skipped.
    """
    if not text:
        return None

    text = text.strip()

    # Skip commands
    if text.startswith("/"):
        return None

    # Skip URLs
    if re.search(r"https?://\S+", text):
        return None

    # Skip very short messages
    if len(text) < 3:
        return None

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text if text else None


async def learn_message(text: str, learned_path: str = DEFAULT_LEARNED_PATH):
    """
    Append a cleaned message to the learned corpus file.
    Safe to call frequently; performs non-blocking I/O.
    """
    cleaned = _clean_message(text)
    if not cleaned:
        return

    try:
        def _append():
            with open(learned_path, "a", encoding="utf-8") as f:
                f.write(cleaned + "\n")

        await asyncio.to_thread(_append)
        logger.debug(f"Learned message: {cleaned[:80]}...")
    except Exception as e:
        logger.error(f"Failed to learn message: {e}")


async def retrain_model(
    output_path: str = DEFAULT_MODEL_PATH,
    base_corpus_path: str = DEFAULT_BASE_CORPUS_PATH,
    learned_path: str = DEFAULT_LEARNED_PATH,
    state_size: int = 2,
) -> bool:
    """
    Retrain the Markov model from the base corpus + learned messages,
    save it to disk, and hot-reload the in-memory model.

    Returns True on success.
    """
    logger.info("Retraining Markov model...")

    corpus_parts = []

    # Read base corpus
    if os.path.exists(base_corpus_path):
        try:

            def _read_base():
                with open(base_corpus_path, "r", encoding="utf-8") as f:
                    return f.read()

            base_text = await asyncio.to_thread(_read_base)
            if base_text.strip():
                corpus_parts.append(base_text.strip())
        except Exception as e:
            logger.error(f"Error reading base corpus: {e}")

    # Read learned messages
    if os.path.exists(learned_path):
        try:

            def _read_learned():
                with open(learned_path, "r", encoding="utf-8") as f:
                    return f.read()

            learned_text = await asyncio.to_thread(_read_learned)
            if learned_text.strip():
                corpus_parts.append(learned_text.strip())
        except Exception as e:
            logger.error(f"Error reading learned corpus: {e}")

    if not corpus_parts:
        logger.warning("No corpus available for retraining")
        return False

    full_corpus = "\n".join(corpus_parts)

    try:

        def _train_and_save():
            model = markovify.NewlineText(full_corpus, state_size=state_size)
            json_str = model.to_json()
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            return model

        new_model = await asyncio.to_thread(_train_and_save)

        # Hot-reload the in-memory model
        global _markov_model, _model_loaded
        _markov_model = new_model
        _model_loaded = True

        logger.info("Markov model retrained and hot-reloaded successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to retrain Markov model: {e}", exc_info=True)
        return False

# src/governance/quality/__init__.py
from .critic import CriticVerdict, score_from_eval, score_from_text, score_from_dict

__all__ = ["CriticVerdict", "score_from_eval", "score_from_text", "score_from_dict"]

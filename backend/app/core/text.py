"""Pure text matching shared by grounded services and credential-free workers."""

import re


def normalize(text):
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())


def phrase_in(phrase, text):
    return f" {normalize(phrase)} " in f" {normalize(text)} "

# backend package
"""
Backend package for the SEC 10-K Analyzer's Bottleneck Monopoly Scanner.

This is deliberately structured as a standalone FastAPI service (see
main.py) with its own SQLite-backed cache (db.py), rather than more Python
functions bolted onto the Streamlit app. Two reasons:

1. The existing single-company analysis flow in app_beautiful_final.py
   already works and is left alone in this pass — this package is purely
   additive.
2. This is the intended foundation for the eventual React frontend: React
   will talk to these same FastAPI endpoints instead of Streamlit, so the
   API surface defined in main.py is worth getting right now rather than
   writing throwaway glue code.
"""

"""
Error classes and FastAPI exception handler
The handler returns a short {detail} message to the UI and logs the full details
Logging setup also goes here
Errors here name what went wrong; routes decide the HTTP response with try/except, so jobs and scripts can use them too
This module imports nothing from repositories or services, so every layer can import from it
"""


# Documents


class DuplicateDocument(Exception):
    # The (owner_id, sha256) constraint rejected a second copy of the same PDF
    pass


class InvalidCursor(ValueError):
    # A pagination cursor that get_all didn't produce, or that was altered
    pass


# Profiles


class UsernameTaken(Exception):
    pass

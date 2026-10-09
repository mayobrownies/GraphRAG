"""
Authentication and account isolation tests (3.2, 4.1)
Missing, expired or invalid token returns 401 on every /api route
/health works without a token
User B cannot list, query, open, retry or delete user A's documents
Retrieval and graph results never include user A's chunks or entities when user B asks
Username: set, read back, and reject duplicates or bad lengths
"""

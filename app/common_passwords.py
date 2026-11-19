"""Small bundled list of commonly used passwords (NIST SP 800-63B §5.1.1.2 blocklist).

Compared case-insensitively. Deliberately short: it blocks the most-guessed choices without a
network lookup. Only entries of 8+ characters matter, since shorter ones fail the length rule.
"""

COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password", "password1", "password12", "password123", "password!", "passw0rd",
        "p@ssw0rd", "p@ssword", "12345678", "123456789", "1234567890", "0123456789",
        "87654321", "11111111", "00000000", "88888888", "12341234", "11223344",
        "qwertyui", "qwerty12", "qwerty123", "qwertyuiop", "1q2w3e4r", "1qaz2wsx",
        "zaq12wsx", "asdfghjkl", "asdf1234", "zxcvbnm1", "iloveyou", "iloveyou1",
        "sunshine", "princess", "football", "baseball", "superman", "starwars",
        "trustno1", "letmein1", "welcome1", "welcome123", "admin123", "administrator",
        "changeme", "changeme1", "default1", "monkey123", "dragon123", "master123",
        "shadow123", "michael1", "jennifer", "computer", "internet", "whatever",
        "freedom1", "abcd1234", "abc12345", "abcdefgh", "test1234", "testtest",
        "secret123", "cisco123", "ciscocisco", "router123", "network1", "netadmin",
        "letmein123", "qwerty1234", "1234qwer", "q1w2e3r4", "aa123456", "a1b2c3d4",
    }
)

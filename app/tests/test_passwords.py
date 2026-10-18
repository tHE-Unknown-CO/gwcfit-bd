from app.auth.passwords import hash_password, hash_token, verify_password, verify_token


def test_password_hash_round_trip():
    hashed_password = hash_password("pulsefit123")

    assert verify_password("pulsefit123", hashed_password)
    assert not verify_password("wrong-password", hashed_password)


def test_token_hash_supports_long_jwt_like_values():
    token = "x" * 500
    hashed_token = hash_token(token)

    assert verify_token(token, hashed_token)
    assert not verify_token(f"{token}wrong", hashed_token)

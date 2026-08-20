from app.auth.passwords import PasswordService


def test_passwords_use_argon2id_and_never_store_plaintext() -> None:
    service = PasswordService()
    password = "correct horse battery staple"

    password_hash = service.hash(password)

    assert password_hash != password
    assert password_hash.startswith("$argon2id$")
    assert service.verify(password, password_hash)
    assert not service.verify("wrong password", password_hash)


def test_malformed_hash_fails_closed() -> None:
    assert not PasswordService().verify("password", "not-a-password-hash")

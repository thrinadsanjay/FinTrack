import unittest

from app.services import keycloak as keycloak_module
from app.services.keycloak import KeycloakService


class TestKeycloakDecodeProd(unittest.TestCase):
    def test_decode_prod_passes_leeway_via_options(self):
        service = KeycloakService()
        service.is_prod = True
        service._get_jwks = lambda: {"keys": [{"kid": "kid-1"}]}

        original_get_header = keycloak_module.jwt.get_unverified_header
        original_decode = keycloak_module.jwt.decode

        captured = {}

        def fake_get_header(_token):
            return {"kid": "kid-1"}

        def fake_decode(token, key, algorithms=None, options=None, audience=None, issuer=None, subject=None, access_token=None):
            captured["token"] = token
            captured["key"] = key
            captured["algorithms"] = algorithms
            captured["options"] = options
            captured["audience"] = audience
            captured["issuer"] = issuer
            return {"sub": "abc"}

        keycloak_module.jwt.get_unverified_header = fake_get_header
        keycloak_module.jwt.decode = fake_decode
        try:
            claims = service._decode_prod("token-value")
        finally:
            keycloak_module.jwt.get_unverified_header = original_get_header
            keycloak_module.jwt.decode = original_decode

        self.assertEqual(claims, {"sub": "abc"})
        self.assertEqual(captured["token"], "token-value")
        self.assertEqual(captured["key"]["kid"], "kid-1")
        self.assertEqual(captured["algorithms"], ["RS256"])
        self.assertEqual(captured["audience"], service.audience)
        self.assertEqual(captured["issuer"], service.issuer)
        self.assertEqual(captured["options"]["leeway"], 60)


if __name__ == "__main__":
    unittest.main()

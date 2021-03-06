
import os
import sys
import hmac
import json
import base64
import urllib
import hashlib
import urlparse
import webbrowser
import wsgiref.util
import wsgiref.simple_server

import requests
import jwcrypto.jwk
import jwcrypto.jwe

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

from browserid.utils import encode_bytes, decode_bytes
import fxa.oauth
from fxa._utils import HawkTokenAuth

import tabulate

ISSUER = 'https://accounts.firefox.com'
CLIENT_ID = '98adfa37698f255b'.lower()
REDIRECT_URI = 'https://lockbox.firefox.com/fxa/ios-redirect.html'
SCOPE = 'https://identity.mozilla.com/apps/oldsync'

CRYPTO_BACKEND = default_backend()


def get_json(url, **kwds):
    r = requests.get(url, **kwds)
    r.raise_for_status()
    return r.json()


class KeyBundle:
    """A little helper class to hold a sync key bundle."""

    def __init__(self, enc_key, mac_key):
        self.enc_key = enc_key
        self.mac_key = mac_key


def decrypt_bso(key_bundle, data):
    "Decrypt a Basic Storage Object payload from sync."""
    payload = json.loads(data["payload"])

    mac = hmac.new(key_bundle.mac_key, payload["ciphertext"], hashlib.sha256)
    if mac.hexdigest() != payload["hmac"]:
        raise ValueError("hmac mismatch")

    iv = base64.b64decode(payload["IV"])
    cipher = Cipher(
        algorithms.AES(key_bundle.enc_key),
        modes.CBC(iv),
        backend=CRYPTO_BACKEND
    )
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(base64.b64decode(payload["ciphertext"]))
    plaintext += decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(plaintext) + unpadder.finalize()

    return json.loads(plaintext)


def authenticate(config):
    """Perform the FxA OAuth dance to get access to sync."""
    client = fxa.oauth.Client(CLIENT_ID,
                              server_url=config["oauth_server_base_url"])

    keys_jwk = jwcrypto.jwk.JWK.generate(kty="EC")
    state = os.urandom(8).encode('hex')
    (pkce_challenge, pkce_verifier) = client.generate_pkce_challenge()

    print "I will now launch the OAuth flow in a new browser window."
    print "When it completes, copy the 'code' parameter from the page URL"
    print "and paste it below."
    print ""
    print "Ready? Hit enter to continue",
    raw_input()

    webbrowser.get().open(client.get_redirect_url(
        state=state,
        scope=SCOPE,
        redirect_uri=REDIRECT_URI,
        access_type="offline",
        keys_jwk=base64.urlsafe_b64encode(keys_jwk.export_public()),
        **pkce_challenge
    ))

    code = raw_input("Code: ")
    tokens = client.trade_code(code, **pkce_verifier)

    keys_jwe = jwcrypto.jwe.JWE()
    keys_jwe.deserialize(tokens.pop("keys_jwe"))
    keys_jwe.decrypt(keys_jwk)
    tokens["keys"] = json.loads(keys_jwe.payload)

    return tokens


def main():
    config = get_json(ISSUER + "/.well-known/fxa-client-configuration")

    if os.path.exists("./credentials.json"):
        with open("./credentials.json") as f:
            creds = json.loads(f.read())
        print "Loaded credentials from ./credentials.json"
    else:
        creds = authenticate(config)
        with open("./credentials.json", "w") as f:
            f.write(json.dumps(creds, indent=4))
        print "Saved credentials to ./credentials.json"

    access_token = creds["access_token"]
    sync_key = jwcrypto.jwk.JWK(**creds["keys"][SCOPE])
    raw_sync_key = decode_bytes(sync_key.get_op_key('encrypt'))
    sync_key_bundle = KeyBundle(
        raw_sync_key[:32],
        raw_sync_key[32:],
    )

    tokenserver_url = config["sync_tokenserver_base_url"]
    sync_creds = get_json(tokenserver_url + '/1.0/sync/1.5', headers={
        'Authorization': 'Bearer ' + access_token,
        'X-KeyID': sync_key.key_id
    })

    auth = HawkTokenAuth(b"0" * (3 * 32), "whatevz")
    auth.id = sync_creds["id"].encode('ascii')
    auth.auth_key = sync_creds["key"].encode('ascii')

    try:
        keys = get_json(sync_creds["api_endpoint"] + "/storage/crypto/keys", auth=auth)
        keys = decrypt_bso(sync_key_bundle, keys)
        default_key_bundle = KeyBundle(
            base64.b64decode(keys["default"][0]),
            base64.b64decode(keys["default"][1]),
        )

        passwords = get_json(sync_creds["api_endpoint"] + "/storage/passwords?full=1", auth=auth)
        if not passwords:
            print "No synced passwords."
        else:
            passwords = [decrypt_bso(default_key_bundle, p) for p in passwords]
            passwords = [(p["id"], p["hostname"], p["username"], p["password"]) for p in passwords if not p.get("deleted", False)]
            print tabulate.tabulate(
                passwords,
                headers=["id", "hostname", "username", "password"],
                tablefmt="grid"
            )
    except requests.exceptions.HTTPError as e:
        if e.response.status_code != 404:
            raise
        print "No synced passwords."


if __name__ == "__main__":
    main()

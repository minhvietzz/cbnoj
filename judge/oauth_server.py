from oauthlib.oauth2 import Server
from oauthlib.oauth2.rfc6749.grant_types.authorization_code import code_challenge_method_s256


class S256OnlyServer(Server):
    """oauthlib server that accepts only PKCE S256 (the stock one also accepts the weak `plain` method)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_grant._code_challenge_methods = {'S256': code_challenge_method_s256}

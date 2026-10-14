WHO = "probe"


def client_owner():
	from . import _client

	return _client.WHO

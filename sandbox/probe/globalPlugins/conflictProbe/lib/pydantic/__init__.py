WHO = "probe"


def __getattr__(name):
	if name == "Model":
		from importlib import import_module

		return import_module(".main", __name__).Model
	raise AttributeError(name)
